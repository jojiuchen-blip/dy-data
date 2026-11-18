from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Any, Mapping

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from apps.api.dy_api.clue_followup_metrics import TerminalEvidence, load_terminal_evidence
from apps.api.dy_api.clue_product_routing import (
    has_published_product_store_list,
    load_product_store_ids,
)

from apps.api.dy_api.models import (
    ClueAllocationDecision,
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueHeadquartersPoolEntry,
    ClueLeadRuleVersionBinding,
    ClueMasterLead,
    DimStore,
    SettlementOrderDetail,
    StoreScoreSnapshot,
    utcnow,
)
from apps.worker.clue_allocation import (
    haversine_km,
    lock_clue_assignment_round_for_update,
    lock_clue_center_order_for_update,
    lock_clue_master_for_update,
    lock_clue_masters_for_update,
    load_product_store_scores,
    normalize_city_code,
    refresh_terminal_evidence_for_locked_lead,
)
from apps.worker.clue_headquarters_pool import (
    close_current_headquarters_pool_entry,
    enter_headquarters_pool,
    get_active_headquarters_pool_entry,
    headquarters_pool_reason_storage_values,
)
from apps.worker.clue_rule_versions import RuleResolutionError, bind_lead_rule_version
from apps.worker.clue_state_locking import refresh_dirty_rounds_for_locked_leads


SELF_OWNED_EXECUTION_MODES = {"formal", "trial"}
FIXED_STRATEGY_TYPES = (
    "sales_store_priority",
    "nearby_city_optimization",
    "city_fallback",
)
DEFAULT_DISTANCE_KM = {
    "sales_store_priority": 10.0,
    "nearby_city_optimization": 15.0,
}


@dataclass(frozen=True)
class AllocationResult:
    lead_key: str
    status: str
    reason: str | None
    selected_store_id: str | None
    assignment_round_id: str | None
    decision_ids: tuple[str, ...] = ()


@dataclass
class _AllocationBatchContext:
    terminal_by_order: dict[str, TerminalEvidence] = field(default_factory=dict)
    stores: list[DimStore] | None = None
    stores_by_id: dict[str, DimStore] = field(default_factory=dict)
    stores_by_city: dict[str, list[DimStore]] = field(default_factory=dict)
    scores_by_rule_version: dict[str, dict[str, StoreScoreSnapshot]] = field(default_factory=dict)


def allocate_lead(
    session: Session,
    lead_key: str,
    *,
    execution_mode: str = "formal",
    allocation_cycle_id: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
    start_after_strategy: str | None = None,
    transition_key: str | None = None,
    auto_expiry_enabled_override: bool | None = None,
    _batch_context: _AllocationBatchContext | None = None,
) -> AllocationResult:
    """Allocate one active M1 lead through its immutable bound rule snapshot.

    This service is deliberately explicit. Collection jobs and clue-center
    projection refreshes do not call it; an operator or allocation-cycle service does.
    """

    normalized_lead_key = _required_text(lead_key, "lead_key")
    normalized_mode = _required_text(execution_mode, "execution_mode")
    if normalized_mode not in SELF_OWNED_EXECUTION_MODES:
        raise ValueError("execution_mode must be formal or trial")
    executed_at = _aware(now or utcnow())
    normalized_cycle = _clean(allocation_cycle_id)
    normalized_actor = _clean(actor) or "manual"
    normalized_transition_key = _clean(transition_key)

    # Every allocation writer begins with a fresh master row and keeps that row
    # locked until the transaction commits.  This serializes against follow-up
    # state transitions and avoids stale identity-map state driving a new round.
    lead = lock_clue_master_for_update(session, normalized_lead_key)
    if lead is None:
        raise ValueError("clue master lead was not found")
    refresh_dirty_rounds_for_locked_leads(session, (lead.lead_key,))
    if lead.routing_mode in {"flow", "direct"}:
        return _allocate_product_routing_locked(
            session, lead, now=executed_at, actor=normalized_actor,
            transition_key=normalized_transition_key or f"first:{lead.lead_key}",
            execution_mode=normalized_mode, allocation_cycle_id=normalized_cycle,
            batch_context=_batch_context,
        )
    terminal = _batch_context.terminal_by_order.get(lead.order_id) if _batch_context is not None else None
    if refresh_terminal_evidence_for_locked_lead(session, lead, now=executed_at, terminal=terminal):
        return AllocationResult(lead_key=lead.lead_key, status="skipped", reason="order_already_terminal",
            selected_store_id=None, assignment_round_id=None)
    if lead.lifecycle_status != "active" or lead.normalized_order_status != "active":
        return AllocationResult(
            lead_key=lead.lead_key,
            status="skipped",
            reason="lead_not_active",
            selected_store_id=None,
            assignment_round_id=None,
        )
    if lead.pool_location == "headquarters_pool" and not _is_retriable_rule_version_unavailable(
        session, lead.lead_key
    ):
        raise ValueError("headquarters_reentry_not_supported")

    current_round = _current_self_owned_round(session, lead)
    if current_round is not None:
        return AllocationResult(
            lead_key=lead.lead_key,
            status="assigned",
            reason="current_self_owned_round_exists",
            selected_store_id=current_round.assigned_store_id,
            assignment_round_id=current_round.assignment_round_id,
            decision_ids=(current_round.allocation_decision_id,) if current_round.allocation_decision_id else (),
        )

    completed_decision = _completed_headquarters_decision(
        session,
        lead_key=lead.lead_key,
        execution_mode=normalized_mode,
        allocation_cycle_id=normalized_cycle,
        transition_key=normalized_transition_key,
    )
    if completed_decision is not None:
        _project_headquarters(lead, executed_at, session, decision=completed_decision)
        session.flush()
        return AllocationResult(
            lead_key=lead.lead_key,
            status="headquarters",
            reason=completed_decision.reason,
            selected_store_id=None,
            assignment_round_id=None,
            decision_ids=(completed_decision.decision_id,),
        )

    try:
        if lead.routing_mode == "original" and session.get(ClueLeadRuleVersionBinding, lead.lead_key) is None:
            raise RuleResolutionError("no published rule was available at first ingress")
        binding = bind_lead_rule_version(
            session,
            lead_key=lead.lead_key,
            anchor_store_id=lead.anchor_store_id,
            anchor_city_code=lead.anchor_city_code,
        )
    except RuleResolutionError:
        decision = _record_headquarters_decision(
            session,
            lead=lead,
            binding=None,
            execution_mode=normalized_mode,
            allocation_cycle_id=normalized_cycle,
            actor=normalized_actor,
            executed_at=executed_at,
            reason="rule_version_unavailable",
            snapshot=_base_snapshot(
                lead=lead,
                binding=None,
                sale_store=_missing_sale_store_evidence(),
                strategy_type="rule_version_resolution",
                enabled=False,
                execution_order=None,
                params={},
                max_distance_km=None,
                historical_store_ids=set(),
                candidates=[],
                selected_store_id=None,
            ),
            strategy_type="rule_version_resolution",
            transition_key=normalized_transition_key,
        )
        _project_headquarters(lead, executed_at, session, decision=decision)
        session.flush()
        return AllocationResult(lead.lead_key, "headquarters", decision.reason, None, None, (decision.decision_id,))

    source_store_mode = any(
        config["strategy_type"] == "nearby_city_optimization"
        and config["params"].get("selection_mode") == "douyin_source_store"
        for config in _strategy_configs(binding.rule_version_snapshot or {})
    )
    anchor_reason = _anchor_unavailable_reason(lead)
    if source_store_mode:
        # Identity-based assignment does not require geographic eligibility.
        anchor_reason = (
            "follow_poi_missing" if not _clean(lead.anchor_poi_id)
            else "follow_poi_unmapped" if not _clean(lead.anchor_store_id)
            else "follow_poi_source_invalid" if lead.anchor_source != "douyin_follow_poi"
            else None
        )
    if anchor_reason:
        snapshot = _base_snapshot(
            lead=lead,
            binding=binding,
            sale_store=_missing_sale_store_evidence(),
            strategy_type="anchor_validation",
            enabled=True,
            execution_order=0,
            params={},
            max_distance_km=None,
            historical_store_ids=set(),
            candidates=[],
            selected_store_id=None,
        )
        decision = _record_headquarters_decision(
            session,
            lead=lead,
            binding=binding,
            execution_mode=normalized_mode,
            allocation_cycle_id=normalized_cycle,
            actor=normalized_actor,
            executed_at=executed_at,
            reason=anchor_reason,
            snapshot=snapshot,
            strategy_type="anchor_validation",
            execution_order=0,
            transition_key=normalized_transition_key,
        )
        _project_headquarters(lead, executed_at, session, decision=decision)
        session.flush()
        return AllocationResult(lead.lead_key, "headquarters", decision.reason, None, None, (decision.decision_id,))

    if not _clean(lead.order_id):
        snapshot = _base_snapshot(
            lead=lead,
            binding=binding,
            sale_store=_missing_sale_store_evidence(),
            strategy_type="allocation_finalization",
            enabled=False,
            execution_order=None,
            params={},
            max_distance_km=None,
            historical_store_ids=set(),
            candidates=[],
            selected_store_id=None,
        )
        decision = _record_headquarters_decision(
            session,
            lead=lead,
            binding=binding,
            execution_mode=normalized_mode,
            allocation_cycle_id=normalized_cycle,
            actor=normalized_actor,
            executed_at=executed_at,
            reason="order_id_missing",
            snapshot=snapshot,
            transition_key=normalized_transition_key,
        )
        _project_headquarters(lead, executed_at, session, decision=decision)
        session.flush()
        return AllocationResult(lead.lead_key, "headquarters", decision.reason, None, None, (decision.decision_id,))

    rule_snapshot = dict(binding.rule_version_snapshot or {})
    strategy_configs = _strategy_configs(rule_snapshot)
    start_after = _clean(start_after_strategy)
    start_after_order: int | None = None
    if start_after:
        matched = next((config for config in strategy_configs if config["strategy_type"] == start_after), None)
        if matched is None:
            raise ValueError("start_after_strategy must be a configured strategy type")
        start_after_order = int(matched["execution_order"])
    if _batch_context is None:
        stores = session.scalars(select(DimStore).order_by(DimStore.store_id)).all()
        stores_by_id, stores_by_city = _index_stores(stores)
        scores = {} if source_store_mode else _latest_scores(
            session,
            {store.store_id for store in stores},
            rule_version_id=binding.rule_version_id,
        )
    else:
        if _batch_context.stores is None:
            _batch_context.stores = session.scalars(select(DimStore).order_by(DimStore.store_id)).all()
            _batch_context.stores_by_id, _batch_context.stores_by_city = _index_stores(
                _batch_context.stores
            )
        stores = _batch_context.stores
        stores_by_id = _batch_context.stores_by_id
        stores_by_city = _batch_context.stores_by_city
        if binding.rule_version_id not in _batch_context.scores_by_rule_version:
            _batch_context.scores_by_rule_version[binding.rule_version_id] = {} if source_store_mode else _latest_scores(
                session,
                {store.store_id for store in stores},
                rule_version_id=binding.rule_version_id,
            )
        scores = _batch_context.scores_by_rule_version[binding.rule_version_id]
    sale_store = _resolve_sale_store_evidence(session, lead.order_id or "")
    historical_store_ids = _historical_self_owned_store_ids(session, lead.lead_key)
    decision_ids: list[str] = []

    for config in strategy_configs:
        strategy_type = config["strategy_type"]
        enabled = config["enabled"]
        execution_order = config["execution_order"]
        params = config["params"]
        max_distance_km = _strategy_distance(strategy_type, params)
        if start_after_order is not None and execution_order <= start_after_order:
            continue

        if not enabled:
            decision = _record_decision(
                session,
                lead=lead,
                binding=binding,
                execution_mode=normalized_mode,
                allocation_cycle_id=normalized_cycle,
                actor=normalized_actor,
                executed_at=executed_at,
                strategy_type=strategy_type,
                execution_order=execution_order,
                status="skipped",
                reason="strategy_disabled",
                snapshot=_base_snapshot(
                    lead=lead,
                    binding=binding,
                    sale_store=sale_store,
                    strategy_type=strategy_type,
                    enabled=False,
                    execution_order=execution_order,
                    params=params,
                    max_distance_km=max_distance_km,
                    historical_store_ids=historical_store_ids,
                    candidates=[],
                    selected_store_id=None,
                ),
                transition_key=normalized_transition_key,
            )
            decision_ids.append(decision.decision_id)
            continue

        candidates, reason, candidate_summary = _strategy_candidates(
            strategy_type=strategy_type,
            lead=lead,
            sale_store=sale_store,
            stores=stores,
            stores_by_id=stores_by_id,
            stores_by_city=stores_by_city,
            scores=scores,
            historical_store_ids=historical_store_ids,
            max_distance_km=max_distance_km,
            source_store_mode=source_store_mode,
        )
        selected = next((candidate for candidate in candidates if candidate["rank"] == 1), None)
        if selected is None:
            decision = _record_decision(
                session,
                lead=lead,
                binding=binding,
                execution_mode=normalized_mode,
                allocation_cycle_id=normalized_cycle,
                actor=normalized_actor,
                executed_at=executed_at,
                strategy_type=strategy_type,
                execution_order=execution_order,
                status="skipped",
                reason=reason or "no_candidate",
                snapshot=_base_snapshot(
                    lead=lead,
                    binding=binding,
                    sale_store=sale_store,
                    strategy_type=strategy_type,
                    enabled=True,
                    execution_order=execution_order,
                    params=params,
                    max_distance_km=max_distance_km,
                    historical_store_ids=historical_store_ids,
                    candidates=candidates,
                    selected_store_id=None,
                    candidate_summary=candidate_summary,
                ),
                transition_key=normalized_transition_key,
            )
            decision_ids.append(decision.decision_id)
            continue

        round_no = _next_round_no(session, lead.lead_key, normalized_mode)
        if source_store_mode and strategy_type == "sales_store_priority" and not historical_store_ids:
            round_no = 0
        assignment_round_id = _assignment_round_id(
            lead_key=lead.lead_key,
            execution_mode=normalized_mode,
            allocation_cycle_id=normalized_cycle,
            round_no=round_no,
        )
        snapshot = _base_snapshot(
            lead=lead,
            binding=binding,
            sale_store=sale_store,
            strategy_type=strategy_type,
            enabled=True,
            execution_order=execution_order,
            params=params,
            max_distance_km=max_distance_km,
            historical_store_ids=historical_store_ids,
            candidates=candidates,
            selected_store_id=selected["store_id"],
            candidate_summary=candidate_summary,
        )
        snapshot["assignment_round"] = {
            "assignment_round_id": assignment_round_id,
            "round_no": round_no,
            "execution_mode": normalized_mode,
            "allocation_cycle_id": normalized_cycle,
        }
        snapshot["execution_timing"] = {
            "auto_expiry_enabled": (
                bool(auto_expiry_enabled_override)
                if auto_expiry_enabled_override is not None
                else bool(rule_snapshot.get("auto_expiry_enabled", True))
            ),
            "source": "cycle_override" if auto_expiry_enabled_override is not None else "rule_version",
        }
        decision = _record_decision(
            session,
            lead=lead,
            binding=binding,
            execution_mode=normalized_mode,
            allocation_cycle_id=normalized_cycle,
            actor=normalized_actor,
            executed_at=executed_at,
            strategy_type=strategy_type,
            execution_order=execution_order,
            status="selected",
            reason="selected",
            selected_store_id=selected["store_id"],
            selected_store_name=selected["store_name"],
            assignment_round_id=assignment_round_id,
            round_no=round_no,
            snapshot=snapshot,
            transition_key=normalized_transition_key,
        )
        round_row = _ensure_selected_round(
            session,
            lead=lead,
            binding=binding,
            decision=decision,
            selected=selected,
            executed_at=executed_at,
            auto_expiry_enabled_override=auto_expiry_enabled_override,
        )
        round_row = lock_clue_assignment_round_for_update(session, round_row.assignment_round_id) or round_row
        _project_self_owned_assignment(lead, round_row, selected, normalized_cycle, executed_at, session)
        session.flush()
        decision_ids.append(decision.decision_id)
        return AllocationResult(
            lead_key=lead.lead_key,
            status="assigned",
            reason="selected",
            selected_store_id=selected["store_id"],
            assignment_round_id=round_row.assignment_round_id,
            decision_ids=tuple(decision_ids),
        )

    final_snapshot = _base_snapshot(
        lead=lead,
        binding=binding,
        sale_store=sale_store,
        strategy_type="allocation_finalization",
        enabled=False,
        execution_order=None,
        params={},
        max_distance_km=None,
        historical_store_ids=historical_store_ids,
        candidates=[],
        selected_store_id=None,
    )
    final = _record_headquarters_decision(
        session,
        lead=lead,
        binding=binding,
        execution_mode=normalized_mode,
        allocation_cycle_id=normalized_cycle,
        actor=normalized_actor,
        executed_at=executed_at,
        reason="no_candidate",
        snapshot=final_snapshot,
        transition_key=normalized_transition_key,
    )
    _project_headquarters(lead, executed_at, session, decision=final)
    session.flush()
    decision_ids.append(final.decision_id)
    return AllocationResult(
        lead_key=lead.lead_key,
        status="headquarters",
        reason=final.reason,
        selected_store_id=None,
        assignment_round_id=None,
        decision_ids=tuple(decision_ids),
    )


def allocate_leads(
    session: Session,
    lead_keys: list[str],
    *,
    execution_mode: str = "formal",
    allocation_cycle_id: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
    auto_expiry_enabled_override: bool | None = None,
) -> list[AllocationResult]:
    """Explicit batch helper for a caller that has already selected M1 leads."""

    batch_context = _AllocationBatchContext()
    indexed_keys = list(enumerate(lead_keys))
    normalized_keys = {
        index: _required_text(lead_key, "lead_key")
        for index, lead_key in indexed_keys
    }
    # Acquire all master locks in one deterministic order before any round or
    # center lock can be taken.  Results retain the caller's order for API
    # compatibility while lock acquisition remains deadlock-safe.
    locked_masters = lock_clue_masters_for_update(session, normalized_keys.values())
    refresh_dirty_rounds_for_locked_leads(session, locked_masters.keys())
    missing = next(
        (lead_key for lead_key in sorted(set(normalized_keys.values())) if lead_key not in locked_masters),
        None,
    )
    if missing is not None:
        raise ValueError("clue master lead was not found")
    batch_context.terminal_by_order = load_terminal_evidence(
        session, {lead.order_id for lead in locked_masters.values() if lead.order_id},
        observed_through=_aware(now or utcnow()),
    )
    results: dict[int, AllocationResult] = {}
    for index, _lead_key in sorted(indexed_keys, key=lambda pair: normalized_keys[pair[0]]):
        results[index] = allocate_lead(
            session,
            normalized_keys[index],
            execution_mode=execution_mode,
            allocation_cycle_id=allocation_cycle_id,
            actor=actor,
            now=now,
            auto_expiry_enabled_override=auto_expiry_enabled_override,
            _batch_context=batch_context,
        )
    return [results[index] for index, _lead_key in indexed_keys]


def continue_product_routing(
    session: Session,
    lead_key: str,
    *,
    now: datetime,
    transition_key: str,
) -> AllocationResult:
    """Continue a flow lead after the caller has invalidated its old task.

    Caller and allocation share one transaction. Repeated delivery cannot
    create another task because the master lock protects the active-task and
    business-round checks.
    """
    lead = lock_clue_master_for_update(session, _required_text(lead_key, "lead_key"))
    if lead is None:
        raise ValueError("clue master lead was not found")
    refresh_dirty_rounds_for_locked_leads(session, (lead.lead_key,))
    if lead.routing_mode != "flow":
        return AllocationResult(lead.lead_key, "skipped", "product_routing_not_enabled", None, None)
    return _allocate_product_routing_locked(
        session, lead, now=_aware(now), actor="product_routing_continuation",
        transition_key=_required_text(transition_key, "transition_key"),
    )


def resume_product_routing(
    session: Session,
    lead_key: str,
    *,
    now: datetime,
    actor: str,
    expected_entry_id: str | None = None,
) -> AllocationResult:
    """Resume headquarters confirmation using current order and list facts."""
    lead = lock_clue_master_for_update(session, _required_text(lead_key, "lead_key"))
    if lead is None:
        raise ValueError("clue master lead was not found")
    refresh_dirty_rounds_for_locked_leads(session, (lead.lead_key,))
    if lead.routing_mode not in {"flow", "direct"}:
        return AllocationResult(lead.lead_key, "skipped", "product_routing_not_supported", None, None)
    executed_at = _aware(now)
    entry = session.scalar(select(ClueHeadquartersPoolEntry)
        .where(ClueHeadquartersPoolEntry.lead_key == lead.lead_key)
        .where(ClueHeadquartersPoolEntry.status == "active")
        .execution_options(populate_existing=True).with_for_update())
    if expected_entry_id is not None and (
        entry is None or entry.headquarters_pool_entry_id != expected_entry_id
    ):
        return AllocationResult(lead.lead_key, "skipped", "headquarters_entry_changed", None, None)
    entry_id = entry.headquarters_pool_entry_id if entry is not None else "none"
    return _allocate_product_routing_locked(
        session, lead, now=executed_at, actor=_required_text(actor, "actor"),
        transition_key=f"resume:{entry_id}:{executed_at.isoformat()}", allow_headquarters=True,
    )


def _allocate_product_routing_locked(
    session: Session,
    lead: ClueMasterLead,
    *,
    now: datetime,
    actor: str,
    transition_key: str,
    execution_mode: str = "formal",
    allocation_cycle_id: str | None = None,
    allow_headquarters: bool = False,
    batch_context: _AllocationBatchContext | None = None,
) -> AllocationResult:
    trial = execution_mode == "trial"
    if not trial and lead.order_id:
        # A repaired source identity must not produce a second task stream
        # for an order already owned by another master.
        if session.get_bind().dialect.name == "postgresql":
            order_lock = int.from_bytes(sha256(f"product-routing:{lead.order_id}".encode()).digest()[:8], "big", signed=True)
            session.execute(select(func.pg_advisory_xact_lock(order_lock)))
        conflicting = session.scalar(select(ClueAssignmentRound.assignment_round_id)
            .where(ClueAssignmentRound.order_id == lead.order_id)
            .where(or_(ClueAssignmentRound.lead_key.is_(None), ClueAssignmentRound.lead_key != lead.lead_key))
            .where(ClueAssignmentRound.execution_mode.in_(("formal", "legacy"))).limit(1))
        if conflicting is not None:
            return AllocationResult(lead.lead_key, "skipped", "order_already_has_task_stream", None, None)
    if trial:
        terminal = load_terminal_evidence(session, {lead.order_id}, observed_through=now).get(lead.order_id)
        is_terminal = terminal is not None and terminal.is_terminal
    else:
        is_terminal = refresh_terminal_evidence_for_locked_lead(session, lead, now=now)
    if is_terminal or lead.lifecycle_status != "active" or lead.normalized_order_status != "active":
        return AllocationResult(lead.lead_key, "skipped", "order_already_terminal" if is_terminal else "lead_not_active", None, None)

    # The pointer alone is insufficient after a retry or a stale projection.
    active = session.scalar(select(ClueAssignmentRound)
        .where(ClueAssignmentRound.lead_key == lead.lead_key)
        .where(ClueAssignmentRound.execution_mode == "formal")
        .where(ClueAssignmentRound.round_status.in_(("active_unfollowed", "active_followed")))
        .order_by(ClueAssignmentRound.round_no.desc())
        .execution_options(populate_existing=True).with_for_update())
    if active is not None and not trial:
        return AllocationResult(lead.lead_key, "assigned", "current_self_owned_round_exists",
            active.assigned_store_id, active.assignment_round_id,
            (active.allocation_decision_id,) if active.allocation_decision_id else ())
    if not trial:
        previous_attempts = session.scalars(select(ClueAllocationDecision)
            .where(ClueAllocationDecision.lead_key == lead.lead_key)
            .where(ClueAllocationDecision.execution_mode == "formal")
            .where(ClueAllocationDecision.decision_status.in_(("assigned", "headquarters", "closed"))))
        replay = next((decision for decision in previous_attempts
            if (decision.decision_snapshot or {}).get("product_routing", {}).get("transition_key") == transition_key), None)
        if replay is not None:
            return AllocationResult(lead.lead_key, "skipped", "transition_already_processed",
                replay.selected_store_id, replay.assignment_round_id, (replay.decision_id,))

    entry = get_active_headquarters_pool_entry(session, lead.lead_key)
    if not trial and not allow_headquarters and lead.pool_location == "headquarters_pool":
        return AllocationResult(lead.lead_key, "headquarters", entry.reason if entry else lead.anchor_unavailable_reason,
            None, None, (entry.source_decision_id,) if entry and entry.source_decision_id else ())

    previous = session.scalar(select(ClueAssignmentRound)
        .where(ClueAssignmentRound.lead_key == lead.lead_key)
        .where(ClueAssignmentRound.execution_mode == "formal")
        .order_by(ClueAssignmentRound.round_no.desc()).limit(1))
    start_round = int(previous.round_no) + 1 if previous is not None else 0
    if entry is not None:
        pending = (entry.source_snapshot or {}).get("product_routing", {}).get("pending_round_no")
        if isinstance(pending, int):
            start_round = max(start_round, pending)
    binding = session.get(ClueLeadRuleVersionBinding, lead.lead_key)
    history = set(session.scalars(select(ClueAssignmentRound.assigned_store_id)
        .where(ClueAssignmentRound.lead_key == lead.lead_key)
        .where(ClueAssignmentRound.execution_mode.in_(("formal", "legacy")))))
    history.discard(None)
    if batch_context is not None and batch_context.stores is not None:
        stores, stores_by_id, stores_by_city = (batch_context.stores,
            batch_context.stores_by_id, batch_context.stores_by_city)
    else:
        stores = list(session.scalars(select(DimStore).order_by(DimStore.store_id)))
        stores_by_id, stores_by_city = _index_stores(stores)
        if batch_context is not None:
            batch_context.stores = stores
            batch_context.stores_by_id, batch_context.stores_by_city = stores_by_id, stores_by_city
    sale_store = _resolve_sale_store_evidence(session, lead.order_id or "")
    decisions: list[str] = []

    def record(status: str, reason: str | None, business_round: int, *,
        candidates: list[dict[str, Any]] | None = None, selected: dict[str, Any] | None = None,
        strategy_type: str = "product_routing_validation") -> ClueAllocationDecision:
        snapshot = _base_snapshot(lead=lead, binding=binding, sale_store=sale_store,
            strategy_type=strategy_type, enabled=True, execution_order=business_round,
            params={}, max_distance_km=10.0 if business_round in (0, 1) else None,
            historical_store_ids=history, candidates=candidates or [],
            selected_store_id=selected["store_id"] if selected else None)
        snapshot["product_routing"] = {"product_id": lead.routing_product_id,
            "routing_mode": lead.routing_mode, "pending_round_no": business_round,
            "business_round_no": business_round, "transition_key": transition_key}
        round_id = _assignment_round_id(lead_key=lead.lead_key, execution_mode=execution_mode,
            allocation_cycle_id=allocation_cycle_id, round_no=business_round) if selected and not trial else None
        if selected:
            snapshot["assignment_round"] = {"assignment_round_id": round_id,
                "round_no": business_round, "execution_mode": execution_mode,
                "allocation_cycle_id": allocation_cycle_id}
            snapshot["execution_timing"] = {"auto_expiry_enabled": lead.routing_mode == "flow" and not trial,
                "first_follow_up_sla_hours": (binding.rule_version_snapshot or {}).get("first_follow_up_sla_hours", 24) if binding else 24}
        decision = _record_decision(session, lead=lead, binding=binding,
            execution_mode=execution_mode, allocation_cycle_id=allocation_cycle_id,
            actor=actor, executed_at=now, strategy_type=strategy_type,
            execution_order=business_round, status=status, reason=reason, snapshot=snapshot,
            selected_store_id=selected["store_id"] if selected else None,
            selected_store_name=selected["store_name"] if selected else None,
            assignment_round_id=round_id, round_no=business_round if selected else None,
            transition_key=transition_key)
        decisions.append(decision.decision_id)
        return decision

    def headquarters(reason: str) -> AllocationResult:
        decision = record("headquarters", reason, start_round)
        if not trial:
            _project_headquarters(lead, now, session, decision=decision)
        session.flush()
        return AllocationResult(lead.lead_key, "headquarters", reason, None, None, tuple(decisions))

    def assign(selected: dict[str, Any], business_round: int, strategy_type: str,
        candidates: list[dict[str, Any]]) -> AllocationResult:
        decision = record("assigned", None, business_round, candidates=candidates,
            selected=selected, strategy_type=strategy_type)
        round_row = None
        if not trial:
            round_row = _ensure_selected_round(session, lead=lead, binding=binding,
                decision=decision, selected=selected, executed_at=now,
                auto_expiry_enabled_override=lead.routing_mode == "flow")
            _project_self_owned_assignment(lead, round_row, selected, allocation_cycle_id, now, session)
        session.flush()
        return AllocationResult(lead.lead_key, "assigned", None, selected["store_id"],
            round_row.assignment_round_id if round_row else None, tuple(decisions))

    if not lead.order_id:
        return headquarters("order_id_missing")
    if lead.routing_mode == "direct":
        if previous is not None:
            return AllocationResult(lead.lead_key, "skipped", "direct_task_already_completed", None, None)
        store = stores_by_id.get(lead.anchor_store_id)
        if not lead.anchor_poi_id or store is None:
            return headquarters("follow_poi_missing" if not lead.anchor_poi_id else "follow_poi_unmapped")
        if not store.is_active or not store.participates_in_clue_allocation:
            return headquarters("source_store_ineligible")
        candidate = {"store_id": store.store_id, "store_name": store.store_name,
            "city_code": normalize_city_code(store.city_code), "eligible": True,
            "exclusion_reasons": [], "distance_km": None,
            "score": _score_snapshot_payload(None, used_for_ranking=False), "rank": 1}
        return assign(candidate, 0, "original_store_direct", [candidate])

    if binding is None:
        return headquarters("rule_version_unavailable")
    if not has_published_product_store_list(session, lead.routing_product_id):
        return headquarters("product_store_list_missing")
    anchor_reason = _anchor_unavailable_reason(lead)
    if anchor_reason:
        return headquarters(anchor_reason)
    allowed_store_ids = load_product_store_ids(session, lead.routing_product_id)
    score_key = f"product:{binding.rule_version_id}:{(binding.rule_version_snapshot or {}).get('product_scope', 'jingcheng')}"
    scores = batch_context.scores_by_rule_version.get(score_key) if batch_context is not None else None
    if scores is None:
        scores = load_product_store_scores(session, stores, rule_version_id=binding.rule_version_id,
            rule_snapshot=binding.rule_version_snapshot or {}, now=now)
        if batch_context is not None:
            batch_context.scores_by_rule_version[score_key] = scores
    for business_round in range(start_round, 3):
        strategy_type = FIXED_STRATEGY_TYPES[business_round]
        candidates, reason, _summary = _strategy_candidates(strategy_type=strategy_type,
            lead=lead, sale_store=sale_store, stores=stores, stores_by_id=stores_by_id,
            stores_by_city=stores_by_city, scores=scores, historical_store_ids=history,
            max_distance_km=10.0 if business_round < 2 else None,
            allowed_store_ids=allowed_store_ids)
        selected = next((candidate for candidate in candidates if candidate["rank"] == 1), None)
        if selected is not None:
            return assign(selected, business_round, strategy_type, candidates)
        record("skipped", reason or "no_candidate", business_round,
            candidates=candidates, strategy_type=strategy_type)
    decision = record("closed", "product_routing_no_candidate", max(start_round, 2),
        strategy_type="product_routing_finalization")
    if not trial:
        _close_product_routing_lead(session, lead, now=now, reason=decision.reason,
            had_assignment=previous is not None)
    session.flush()
    return AllocationResult(lead.lead_key, "closed", decision.reason, None, None, tuple(decisions))


def _close_product_routing_lead(session: Session, lead: ClueMasterLead, *, now: datetime,
    reason: str, had_assignment: bool) -> None:
    close_current_headquarters_pool_entry(session, lead.lead_key, closed_at=now, close_reason=reason)
    lead.lifecycle_status, lead.allocation_state, lead.pool_location = "closed_order", "closed", "closed"
    lead.current_assignment_round_id = None
    lead.closed_at = lead.closed_at or now
    lead.closed_reason = reason
    lead.ended_without_assignment = not had_assignment
    lead.state_version = max(lead.state_version or 1, 1) + 1
    lead.updated_at = now
    center = lock_clue_center_order_for_update(session, lead.order_id)
    if center is not None:
        center.lead_status = "closed"
        center.current_round_status = "closed_no_candidate"
        center.reassign_reason = reason
        center.updated_at = now


def _strategy_configs(rule_snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_type: dict[str, Mapping[str, Any]] = {}
    raw_configs = rule_snapshot.get("strategy_configs", [])
    if isinstance(raw_configs, list):
        for raw_config in raw_configs:
            if isinstance(raw_config, Mapping) and raw_config.get("strategy_type") in FIXED_STRATEGY_TYPES:
                by_type[str(raw_config["strategy_type"])] = raw_config

    configs: list[dict[str, Any]] = []
    for index, strategy_type in enumerate(FIXED_STRATEGY_TYPES, start=1):
        config = by_type.get(strategy_type, {})
        params = config.get("params") if isinstance(config.get("params"), Mapping) else {}
        execution_order = config.get("execution_order")
        configs.append(
            {
                "strategy_type": strategy_type,
                "enabled": bool(config.get("enabled")) if config else False,
                "execution_order": int(execution_order) if isinstance(execution_order, int) else index,
                "params": dict(params),
            }
        )
    return sorted(configs, key=lambda config: (config["execution_order"], config["strategy_type"]))


def _strategy_candidates(
    *,
    strategy_type: str,
    lead: ClueMasterLead,
    sale_store: dict[str, Any],
    stores: list[DimStore],
    stores_by_id: Mapping[str, DimStore],
    stores_by_city: Mapping[str, list[DimStore]],
    scores: dict[str, StoreScoreSnapshot],
    historical_store_ids: set[str],
    max_distance_km: float | None,
    source_store_mode: bool = False,
    allowed_store_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str | None, dict[str, int]]:
    if source_store_mode and strategy_type != "sales_store_priority":
        # No city fallback may silently replace the exact Douyin source store.
        if strategy_type != "nearby_city_optimization":
            return [], "source_store_only", _candidate_summary(stores, [], in_scope_count=0)
        store = stores_by_id.get(lead.anchor_store_id)
        if store is None:
            candidate = _unknown_store_candidate(
                store_id=lead.anchor_store_id, reason="follow_poi_store_missing", used_for_ranking=False
            )
        else:
            reasons = []
            if not store.is_active:
                reasons.append("store_inactive")
            if not store.participates_in_clue_allocation:
                reasons.append("allocation_participation_disabled")
            if store.store_id in historical_store_ids:
                reasons.append("historically_self_owned")
            candidate = {
                "store_id": store.store_id, "store_name": store.store_name,
                "city_code": normalize_city_code(store.city_code),
                "eligible": not reasons, "exclusion_reasons": reasons,
                "distance_km": None, "score": _score_snapshot_payload(None, used_for_ranking=False),
                "rank": None if reasons else 1,
            }
        return [candidate], None if candidate["eligible"] else "source_store_ineligible", _candidate_summary(
            stores, [candidate], in_scope_count=1
        )
    if strategy_type == "sales_store_priority":
        if sale_store["status"] != "resolved":
            return [], str(sale_store["status"]), _candidate_summary(stores, [], in_scope_count=0)
        sale_store_id = sale_store.get("store_id")
        store = stores_by_id.get(sale_store_id)
        if store is None:
            candidates = [
                _unknown_store_candidate(
                    store_id=sale_store_id,
                    reason="sale_store_unmapped",
                    used_for_ranking=False,
                )
            ]
            return candidates, "sale_store_unmapped", _candidate_summary(
                stores,
                candidates,
                in_scope_count=1,
            )
        candidate = _candidate_record(
            store,
            lead=lead,
            score=scores.get(store.store_id),
            require_same_city=False,
            exclude_history=True,
            historical_store_ids=historical_store_ids,
            max_distance_km=max_distance_km,
            used_for_ranking=False,
            allowed_store_ids=allowed_store_ids,
        )
        if not candidate["eligible"]:
            if "distance_exceeds_max" in candidate["exclusion_reasons"]:
                reason = "sale_store_over_distance"
            elif "historically_self_owned" in candidate["exclusion_reasons"]:
                reason = "sale_store_previously_assigned"
            else:
                reason = "sale_store_ineligible"
            candidates = [candidate]
            return candidates, reason, _candidate_summary(stores, candidates, in_scope_count=1)
        candidate["rank"] = 1
        candidates = [candidate]
        return candidates, None, _candidate_summary(stores, candidates, in_scope_count=1)

    scoped_stores = list(stores_by_city.get(normalize_city_code(lead.anchor_city_code), []))
    candidates = [
        _candidate_record(
            store,
            lead=lead,
            score=scores.get(store.store_id),
            require_same_city=True,
            exclude_history=True,
            historical_store_ids=historical_store_ids,
            max_distance_km=max_distance_km,
            used_for_ranking=True,
            allowed_store_ids=allowed_store_ids,
        )
        for store in scoped_stores
    ]
    ranked = [candidate for candidate in candidates if candidate["eligible"]]
    ranked.sort(
        key=lambda candidate: (
            -float(candidate["score"]["composite_score"]),
            float(candidate["distance_km"]),
            str(candidate["store_id"]),
        )
    )
    for rank, candidate in enumerate(ranked, start=1):
        candidate["rank"] = rank
    return (
        candidates,
        None if ranked else "no_candidate",
        _candidate_summary(
            stores,
            candidates,
            in_scope_count=len(scoped_stores),
            omitted_out_of_city_count=len(stores) - len(scoped_stores),
        ),
    )


def _index_stores(stores: list[DimStore]) -> tuple[dict[str, DimStore], dict[str, list[DimStore]]]:
    stores_by_id = {store.store_id: store for store in stores}
    stores_by_city: dict[str, list[DimStore]] = {}
    for store in stores:
        city_code = normalize_city_code(store.city_code)
        stores_by_city.setdefault(city_code, []).append(store)
    return stores_by_id, stores_by_city


def _candidate_summary(
    stores: list[DimStore],
    candidates: list[dict[str, Any]],
    *,
    in_scope_count: int,
    omitted_out_of_city_count: int = 0,
) -> dict[str, int]:
    return {
        "store_universe_count": len(stores),
        "in_scope_store_count": in_scope_count,
        "omitted_out_of_city_count": max(omitted_out_of_city_count, 0),
        "evaluated_count": len(candidates),
        "eligible_count": sum(1 for candidate in candidates if candidate["eligible"]),
    }


def _candidate_record(
    store: DimStore,
    *,
    lead: ClueMasterLead,
    score: StoreScoreSnapshot | None,
    require_same_city: bool,
    exclude_history: bool,
    historical_store_ids: set[str],
    max_distance_km: float | None,
    used_for_ranking: bool,
    allowed_store_ids: set[str] | None = None,
) -> dict[str, Any]:
    reasons = _candidate_eligibility_reasons(store)
    if allowed_store_ids is not None and store.store_id not in allowed_store_ids:
        reasons.append("product_store_not_applicable")
    distance_km: float | None = None
    if not reasons:
        distance_km = _distance_from_anchor(lead, store)
        if distance_km is None:
            reasons.append("anchor_coordinates_unavailable")
    if require_same_city and normalize_city_code(store.city_code) != normalize_city_code(lead.anchor_city_code):
        reasons.append("city_mismatch")
    if exclude_history and store.store_id in historical_store_ids:
        reasons.append("historically_self_owned")
    if max_distance_km is not None and distance_km is not None and distance_km > max_distance_km:
        reasons.append("distance_exceeds_max")
    return {
        "store_id": store.store_id,
        "store_name": store.store_name,
        "city_code": normalize_city_code(store.city_code),
        "eligible": not reasons,
        "exclusion_reasons": reasons,
        "distance_km": round(distance_km, 6) if distance_km is not None else None,
        "score": _score_snapshot_payload(score, used_for_ranking=used_for_ranking),
        "rank": None,
    }


def _unknown_store_candidate(*, store_id: str | None, reason: str, used_for_ranking: bool) -> dict[str, Any]:
    return {
        "store_id": store_id,
        "store_name": None,
        "city_code": None,
        "eligible": False,
        "exclusion_reasons": [reason],
        "distance_km": None,
        "score": _score_snapshot_payload(None, used_for_ranking=used_for_ranking),
        "rank": None,
    }


def _candidate_eligibility_reasons(store: DimStore) -> list[str]:
    reasons: list[str] = []
    if not store.is_active:
        reasons.append("store_inactive")
    if not store.is_douyin_clue_applicable:
        reasons.append("douyin_clue_not_applicable")
    if not store.participates_in_clue_allocation:
        reasons.append("allocation_participation_disabled")
    if store.location_status != "valid":
        reasons.append("location_not_valid")
    if not _clean(store.standard_province):
        reasons.append("province_missing")
    if not _clean(store.standard_city):
        reasons.append("city_missing")
    if not normalize_city_code(store.city_code):
        reasons.append("city_code_missing")
    if not _valid_coordinates(store.latitude, store.longitude):
        reasons.append("coordinates_invalid")
    return reasons


def _distance_from_anchor(lead: ClueMasterLead, store: DimStore) -> float | None:
    if not _valid_coordinates(lead.anchor_latitude, lead.anchor_longitude):
        return None
    if not _valid_coordinates(store.latitude, store.longitude):
        return None
    return haversine_km(
        float(lead.anchor_latitude),
        float(lead.anchor_longitude),
        float(store.latitude),
        float(store.longitude),
    )


def _score_snapshot_payload(snapshot: StoreScoreSnapshot | None, *, used_for_ranking: bool) -> dict[str, Any]:
    if snapshot is None:
        return {
            "used_for_ranking": used_for_ranking,
            "snapshot_id": None,
            "snapshot_run_id": None,
            "rule_version_id": None,
            "snapshot_date": None,
            "computed_at": None,
            "composite_score": 0.0,
            "conversion_rate": 0.0,
            "conversion_value_source": "score_snapshot_missing",
            "follow_24h_rate": 0.0,
            "follow_24h_value_source": "score_snapshot_missing",
            "store_weight": 1.0,
        }
    return {
        "used_for_ranking": used_for_ranking,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_run_id": snapshot.snapshot_run_id,
        "rule_version_id": _score_snapshot_rule_version_id(snapshot),
        "snapshot_date": snapshot.snapshot_date.isoformat() if snapshot.snapshot_date else None,
        "computed_at": _iso_datetime(snapshot.computed_at),
        "composite_score": float(snapshot.composite_score),
        "conversion_rate": float(snapshot.conversion_rate),
        "conversion_value_source": snapshot.conversion_value_source,
        "follow_24h_rate": float(snapshot.follow_24h_rate),
        "follow_24h_value_source": snapshot.follow_24h_value_source,
        "store_weight": float(snapshot.store_weight),
        "product_scope": (snapshot.config_json or {}).get("product_scope"),
        "metric_version": (snapshot.config_json or {}).get("metric_version"),
        "conversion_numerator": snapshot.conversion_numerator,
        "conversion_denominator": snapshot.conversion_denominator,
        "follow_24h_numerator": snapshot.follow_24h_numerator,
        "follow_24h_denominator": snapshot.follow_24h_denominator,
    }


def _latest_scores(
    session: Session,
    store_ids: set[str],
    *,
    rule_version_id: str,
) -> dict[str, StoreScoreSnapshot]:
    if not store_ids:
        return {}
    rows = session.scalars(
        select(StoreScoreSnapshot)
        .where(StoreScoreSnapshot.store_id.in_(store_ids))
        .order_by(StoreScoreSnapshot.store_id, StoreScoreSnapshot.computed_at.desc(), StoreScoreSnapshot.snapshot_id.desc())
    ).all()
    latest: dict[str, StoreScoreSnapshot] = {}
    for row in rows:
        if _score_snapshot_rule_version_id(row) != rule_version_id:
            continue
        latest.setdefault(row.store_id, row)
    return latest


def _score_snapshot_rule_version_id(snapshot: StoreScoreSnapshot) -> str | None:
    config = snapshot.config_json if isinstance(snapshot.config_json, dict) else {}
    value = config.get("rule_version_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _resolve_sale_store_evidence(session: Session, order_id: str) -> dict[str, Any]:
    store_ids: set[str] = set()
    for raw_store_id in session.scalars(
        select(SettlementOrderDetail.sale_store_id).where(SettlementOrderDetail.order_id == order_id)
    ).all():
        store_id = _clean(raw_store_id)
        if store_id:
            store_ids.add(store_id)
    ordered_store_ids = sorted(store_ids)
    if not ordered_store_ids:
        return _missing_sale_store_evidence()
    if len(ordered_store_ids) > 1:
        return {
            "status": "sale_store_ambiguous",
            "store_id": None,
            "store_ids": ordered_store_ids,
            "source": "settlement_order_details",
        }
    return {
        "status": "resolved",
        "store_id": ordered_store_ids[0],
        "store_ids": ordered_store_ids,
        "source": "settlement_order_details",
    }


def _missing_sale_store_evidence() -> dict[str, Any]:
    return {
        "status": "sale_store_missing",
        "store_id": None,
        "store_ids": [],
        "source": "settlement_order_details",
    }


def _historical_self_owned_store_ids(session: Session, lead_key: str) -> set[str]:
    store_ids: set[str] = set()
    for raw_store_id in session.scalars(
        select(ClueAssignmentRound.assigned_store_id)
        .where(ClueAssignmentRound.lead_key == lead_key)
        .where(ClueAssignmentRound.execution_mode.in_(SELF_OWNED_EXECUTION_MODES))
    ).all():
        store_id = _clean(raw_store_id)
        if store_id:
            store_ids.add(store_id)
    return store_ids


def _base_snapshot(
    *,
    lead: ClueMasterLead,
    binding: ClueLeadRuleVersionBinding | None,
    sale_store: dict[str, Any],
    strategy_type: str,
    enabled: bool,
    execution_order: int | None,
    params: Mapping[str, Any],
    max_distance_km: float | None,
    historical_store_ids: set[str],
    candidates: list[dict[str, Any]],
    selected_store_id: str | None,
    candidate_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "anchor": {
            "poi_id": lead.anchor_poi_id,
            "store_id": lead.anchor_store_id,
            "province": lead.anchor_province,
            "city": lead.anchor_city,
            "city_code": lead.anchor_city_code,
            "longitude": _decimal_to_float(lead.anchor_longitude),
            "latitude": _decimal_to_float(lead.anchor_latitude),
            "unavailable_reason": lead.anchor_unavailable_reason,
        },
        "sale_store": dict(sale_store),
        "rule_version": _rule_snapshot_payload(binding),
        "strategy": {
            "strategy_type": strategy_type,
            "enabled": enabled,
            "execution_order": execution_order,
            "params": dict(params),
            "max_distance_km": max_distance_km,
        },
        "historical_self_owned_store_ids": sorted(historical_store_ids),
        "candidate_summary": dict(candidate_summary or {}),
        "candidates": candidates,
        "selected_store_id": selected_store_id,
    }


def _rule_snapshot_payload(binding: ClueLeadRuleVersionBinding | None) -> dict[str, Any] | None:
    if binding is None:
        return None
    snapshot = dict(binding.rule_version_snapshot or {})
    return {
        "rule_id": (binding.scope_resolution_snapshot or {}).get("rule_id"),
        "rule_version_id": binding.rule_version_id,
        "version_no": snapshot.get("version_no"),
        "scope": dict(binding.scope_resolution_snapshot or {}),
        "timing": {
            "auto_expiry_enabled": snapshot.get("auto_expiry_enabled"),
            "first_follow_up_sla_hours": snapshot.get("first_follow_up_sla_hours"),
            "protection_days": snapshot.get("protection_days"),
            "lookback_days": snapshot.get("lookback_days"),
            "min_samples": snapshot.get("min_samples"),
            "conversion_weight": snapshot.get("conversion_weight"),
            "follow_24h_weight": snapshot.get("follow_24h_weight"),
        },
    }


def _record_headquarters_decision(
    session: Session,
    *,
    lead: ClueMasterLead,
    binding: ClueLeadRuleVersionBinding | None,
    execution_mode: str,
    allocation_cycle_id: str | None,
    actor: str,
    executed_at: datetime,
    reason: str,
    snapshot: dict[str, Any],
    strategy_type: str = "allocation_finalization",
    execution_order: int | None = None,
    transition_key: str | None = None,
) -> ClueAllocationDecision:
    return _record_decision(
        session,
        lead=lead,
        binding=binding,
        execution_mode=execution_mode,
        allocation_cycle_id=allocation_cycle_id,
        actor=actor,
        executed_at=executed_at,
        strategy_type=strategy_type,
        execution_order=execution_order,
        status="headquarters",
        reason=reason,
        snapshot=snapshot,
        transition_key=transition_key,
    )


def _record_decision(
    session: Session,
    *,
    lead: ClueMasterLead,
    binding: ClueLeadRuleVersionBinding | None,
    execution_mode: str,
    allocation_cycle_id: str | None,
    actor: str,
    executed_at: datetime,
    strategy_type: str,
    execution_order: int | None,
    status: str,
    reason: str | None,
    snapshot: dict[str, Any],
    selected_store_id: str | None = None,
    selected_store_name: str | None = None,
    assignment_round_id: str | None = None,
    round_no: int | None = None,
    transition_key: str | None = None,
) -> ClueAllocationDecision:
    attempt_key = _attempt_key(
        lead_key=lead.lead_key,
        execution_mode=execution_mode,
        allocation_cycle_id=allocation_cycle_id,
        strategy_type=strategy_type,
        execution_order=execution_order,
        transition_key=transition_key,
    )
    existing = session.scalar(select(ClueAllocationDecision).where(ClueAllocationDecision.attempt_key == attempt_key))
    if existing is not None:
        return existing

    rule_scope = dict(binding.scope_resolution_snapshot or {}) if binding is not None else {}
    decision = ClueAllocationDecision(
        decision_id=f"allocation-decision-{sha256(attempt_key.encode('utf-8')).hexdigest()[:24]}",
        attempt_key=attempt_key,
        lead_key=lead.lead_key,
        order_id=lead.order_id,
        rule_id=rule_scope.get("rule_id"),
        rule_version_id=binding.rule_version_id if binding is not None else None,
        scope_type=binding.scope_type if binding is not None else None,
        scope_key=binding.scope_key if binding is not None else None,
        strategy_type=strategy_type,
        execution_order=execution_order,
        allocation_cycle_id=allocation_cycle_id,
        execution_mode=execution_mode,
        assignment_round_id=assignment_round_id,
        round_no=round_no,
        selected_store_id=selected_store_id,
        selected_store_name=selected_store_name,
        decision_status=status,
        reason=reason,
        decision_snapshot=snapshot,
        actor=actor,
        executed_at=executed_at,
    )
    try:
        with session.begin_nested():
            session.add(decision)
            session.flush()
    except IntegrityError:
        winner = session.scalar(select(ClueAllocationDecision).where(ClueAllocationDecision.attempt_key == attempt_key))
        if winner is not None:
            return winner
        raise
    return decision


def _ensure_selected_round(
    session: Session,
    *,
    lead: ClueMasterLead,
    binding: ClueLeadRuleVersionBinding | None,
    decision: ClueAllocationDecision,
    selected: dict[str, Any],
    executed_at: datetime,
    auto_expiry_enabled_override: bool | None = None,
) -> ClueAssignmentRound:
    if not decision.assignment_round_id or decision.round_no is None:
        raise RuntimeError("selected allocation decision must contain its round identity")
    existing = lock_clue_assignment_round_for_update(session, decision.assignment_round_id)
    if existing is not None:
        return existing

    rule_snapshot = dict(binding.rule_version_snapshot or {}) if binding is not None else {}
    first_follow_up_sla_hours = _positive_int(rule_snapshot.get("first_follow_up_sla_hours"), 24)
    protection_days = _positive_int(rule_snapshot.get("protection_days"), 7)
    round_row = ClueAssignmentRound(
        assignment_round_id=decision.assignment_round_id,
        order_id=lead.order_id or "",
        lead_key=lead.lead_key,
        rule_version_id=binding.rule_version_id if binding is not None else None,
        strategy_type=decision.strategy_type,
        allocation_decision_id=decision.decision_id,
        allocation_cycle_id=decision.allocation_cycle_id,
        round_no=decision.round_no,
        assigned_at=executed_at,
        assigned_at_source="clue_allocation_engine",
        assigned_store_id=selected["store_id"],
        assigned_store_name=selected["store_name"],
        follow_result="pending",
        is_followed=False,
        is_follow_success=False,
        round_status="active_unfollowed",
        execution_mode=decision.execution_mode,
        expires_at=executed_at + timedelta(hours=first_follow_up_sla_hours),
        first_sla_expires_at=executed_at + timedelta(hours=first_follow_up_sla_hours),
        auto_expiry_enabled=(
            bool(auto_expiry_enabled_override)
            if auto_expiry_enabled_override is not None
            else bool(rule_snapshot.get("auto_expiry_enabled", True))
        ),
        first_follow_up_sla_hours=first_follow_up_sla_hours,
        protection_days=protection_days,
        created_at=executed_at,
        updated_at=executed_at,
    )
    try:
        with session.begin_nested():
            session.add(round_row)
            session.flush()
    except IntegrityError:
        winner = lock_clue_assignment_round_for_update(session, decision.assignment_round_id)
        if winner is not None:
            return winner
        raise
    return round_row


def _project_self_owned_assignment(
    lead: ClueMasterLead,
    round_row: ClueAssignmentRound,
    selected: Mapping[str, Any],
    allocation_cycle_id: str | None,
    executed_at: datetime,
    session: Session,
) -> None:
    close_current_headquarters_pool_entry(
        session,
        lead.lead_key,
        closed_at=executed_at,
        close_reason="allocated_to_store",
    )
    lead.pool_location = "store_follow_up_pool"
    lead.allocation_state = "assigned"
    lead.current_assignment_round_id = round_row.assignment_round_id
    lead.allocation_cycle_id = allocation_cycle_id
    lead.ended_without_assignment = False
    lead.updated_at = executed_at

    center_order = lock_clue_center_order_for_update(session, round_row.order_id)
    if center_order is None:
        # A same-session batch may have just created this order projection and
        # not flushed it yet.  Reuse that pending identity instead of creating
        # a second object with the same primary key.
        center_order = next(
            (
                pending
                for pending in session.new
                if isinstance(pending, ClueCenterOrder) and pending.order_id == round_row.order_id
            ),
            None,
        )
    if center_order is None:
        center_order = ClueCenterOrder(
            order_id=round_row.order_id,
            lead_status="active",
            current_round_status="active_unfollowed",
            created_at=executed_at,
            updated_at=executed_at,
        )
        session.add(center_order)
    existing_center_round = (
        session.scalar(
            select(ClueAssignmentRound)
            .where(ClueAssignmentRound.assignment_round_id == center_order.current_assignment_round_id)
            .execution_options(populate_existing=True)
        )
        if center_order.current_assignment_round_id
        else None
    )
    if (
        existing_center_round is not None
        and existing_center_round.execution_mode in SELF_OWNED_EXECUTION_MODES
        and existing_center_round.lead_key != lead.lead_key
    ):
        # The clue-center compatibility projection is still order-grain. Do not let
        # a second contact-level lead silently overwrite the first self-owned view.
        return

    center_order.lead_status = "active"
    center_order.current_assignment_round_id = round_row.assignment_round_id
    center_order.current_round_no = round_row.round_no
    center_order.current_round_status = round_row.round_status
    center_order.assigned_at = round_row.assigned_at
    center_order.assigned_at_source = round_row.assigned_at_source
    center_order.assigned_store_id = round_row.assigned_store_id
    center_order.assigned_store_name = round_row.assigned_store_name
    center_order.assigned_city = _clean(selected.get("city_code"))
    center_order.assigned_province = _clean(lead.anchor_province)
    center_order.follow_result = round_row.follow_result
    center_order.is_followed = round_row.is_followed
    center_order.is_follow_success = round_row.is_follow_success
    center_order.verified_store_id = None
    center_order.verified_store_name = None
    center_order.verified_at = None
    center_order.is_self_store_verified = False
    center_order.expires_at = None
    center_order.reassign_reason = None
    center_order.updated_at = executed_at


def _project_headquarters(
    lead: ClueMasterLead,
    executed_at: datetime,
    session: Session,
    *,
    decision: ClueAllocationDecision,
) -> None:
    lead.pool_location = "headquarters_pool"
    lead.allocation_state = "headquarters"
    lead.current_assignment_round_id = None
    lead.allocation_cycle_id = decision.allocation_cycle_id
    lead.ended_without_assignment = False
    lead.updated_at = executed_at
    enter_headquarters_pool(
        session,
        lead=lead,
        reason=decision.reason or "headquarters",
        entered_at=executed_at,
        source_decision=decision,
    )
    center_order = None
    if lead.order_id:
        # Read the pointer once to determine which round must be locked, then
        # acquire the canonical master -> round -> center chain.  If the center
        # pointer changed while waiting, leave the newer projection untouched.
        pointer_snapshot = session.scalar(
            select(ClueCenterOrder)
            .where(ClueCenterOrder.order_id == lead.order_id)
            .execution_options(populate_existing=True)
        )
        pointer_round_id = pointer_snapshot.current_assignment_round_id if pointer_snapshot is not None else None
        with session.no_autoflush:
            pointer_owner = session.scalar(
                select(ClueAssignmentRound.lead_key)
                .where(ClueAssignmentRound.assignment_round_id == pointer_round_id)
            ) if pointer_round_id else None
        # An order may have several master records.  Owning this master does
        # not authorize taking another master's child lock out of order.
        if pointer_owner != lead.lead_key:
            return
        pointer_round = (
            lock_clue_assignment_round_for_update(session, pointer_round_id)
            if pointer_round_id
            else None
        )
        if pointer_round is None or pointer_round.lead_key != lead.lead_key:
            return
        center_order = lock_clue_center_order_for_update(session, lead.order_id)
        if (
            center_order is None
            or not center_order.current_assignment_round_id
            or pointer_round is None
            or center_order.current_assignment_round_id != pointer_round.assignment_round_id
        ):
            return
        center_round = pointer_round
    else:
        center_round = None
    if center_round is None or center_round.lead_key != lead.lead_key:
        return
    center_order.current_assignment_round_id = None
    center_order.current_round_no = 0
    center_order.current_round_status = "headquarters"
    center_order.assigned_at = None
    center_order.assigned_store_id = None
    center_order.assigned_store_name = None
    center_order.assigned_city = None
    center_order.assigned_province = None
    center_order.expires_at = None
    center_order.reassign_reason = "headquarters_pool"
    center_order.updated_at = executed_at


def _is_retriable_rule_version_unavailable(session: Session, lead_key: str) -> bool:
    return (
        session.scalar(
            select(ClueHeadquartersPoolEntry.headquarters_pool_entry_id)
            .where(ClueHeadquartersPoolEntry.lead_key == lead_key)
            .where(ClueHeadquartersPoolEntry.status == "active")
            .where(
                ClueHeadquartersPoolEntry.reason.in_(
                    headquarters_pool_reason_storage_values("no_published_rule")
                )
            )
            .limit(1)
        )
        is not None
    )


def _current_self_owned_round(session: Session, lead: ClueMasterLead) -> ClueAssignmentRound | None:
    if not lead.current_assignment_round_id:
        return None
    row = lock_clue_assignment_round_for_update(session, lead.current_assignment_round_id)
    if row is None or row.execution_mode not in SELF_OWNED_EXECUTION_MODES:
        return None
    return row


def _completed_headquarters_decision(
    session: Session,
    *,
    lead_key: str,
    execution_mode: str,
    allocation_cycle_id: str | None,
    transition_key: str | None,
) -> ClueAllocationDecision | None:
    attempt_key = _attempt_key(
        lead_key=lead_key,
        execution_mode=execution_mode,
        allocation_cycle_id=allocation_cycle_id,
        strategy_type="allocation_finalization",
        execution_order=None,
        transition_key=transition_key,
    )
    return session.scalar(select(ClueAllocationDecision).where(ClueAllocationDecision.attempt_key == attempt_key))


def _next_round_no(session: Session, lead_key: str, execution_mode: str) -> int:
    current = session.scalar(
        select(func.max(ClueAssignmentRound.round_no))
        .where(ClueAssignmentRound.lead_key == lead_key)
        .where(ClueAssignmentRound.execution_mode == execution_mode)
    )
    return int(current or 0) + 1


def _assignment_round_id(
    *,
    lead_key: str,
    execution_mode: str,
    allocation_cycle_id: str | None,
    round_no: int,
) -> str:
    value = "|".join((lead_key, execution_mode, allocation_cycle_id or "", str(round_no)))
    return f"allocation-round-{sha256(value.encode('utf-8')).hexdigest()[:24]}"


def _attempt_key(
    *,
    lead_key: str,
    execution_mode: str,
    allocation_cycle_id: str | None,
    strategy_type: str,
    execution_order: int | None,
    transition_key: str | None = None,
) -> str:
    value = "|".join(
        (
            lead_key,
            execution_mode,
            allocation_cycle_id or "",
            strategy_type,
            "" if execution_order is None else str(execution_order),
            transition_key or "",
        )
    )
    return f"clue-allocation:{sha256(value.encode('utf-8')).hexdigest()}"


def _strategy_distance(strategy_type: str, params: Mapping[str, Any]) -> float | None:
    if strategy_type not in DEFAULT_DISTANCE_KM:
        return None
    value = params.get("max_distance_km", DEFAULT_DISTANCE_KM[strategy_type])
    try:
        return float(Decimal(str(value)))
    except Exception:
        return DEFAULT_DISTANCE_KM[strategy_type]


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _anchor_unavailable_reason(lead: ClueMasterLead) -> str | None:
    if lead.anchor_unavailable_reason:
        return lead.anchor_unavailable_reason
    if not _clean(lead.anchor_poi_id):
        return "follow_poi_missing"
    if not _clean(lead.anchor_store_id):
        return "anchor_store_missing"
    if not normalize_city_code(lead.anchor_city_code):
        return "anchor_city_code_missing"
    if not _valid_coordinates(lead.anchor_latitude, lead.anchor_longitude):
        return "anchor_coordinates_unavailable"
    return None


def _valid_coordinates(latitude: Decimal | None, longitude: Decimal | None) -> bool:
    if latitude is None or longitude is None:
        return False
    try:
        return -90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180
    except (TypeError, ValueError):
        return False


def _required_text(value: object, name: str) -> str:
    normalized = _clean(value)
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _iso_datetime(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None
