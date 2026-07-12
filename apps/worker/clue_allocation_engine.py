from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationDecision,
    ClueAssignmentRound,
    ClueCenterOrder,
    ClueLeadRuleVersionBinding,
    ClueMasterLead,
    DimStore,
    SettlementOrderDetail,
    StoreScoreSnapshot,
    utcnow,
)
from apps.worker.clue_allocation import haversine_km, normalize_city_code
from apps.worker.clue_rule_versions import RuleResolutionError, bind_lead_rule_version


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
) -> AllocationResult:
    """Allocate one active M1 lead through its immutable bound rule snapshot.

    This service is deliberately explicit. Collection jobs and legacy clue-center
    rebuilding do not call it; an operator or future allocation-cycle service does.
    """

    normalized_lead_key = _required_text(lead_key, "lead_key")
    normalized_mode = _required_text(execution_mode, "execution_mode")
    if normalized_mode not in SELF_OWNED_EXECUTION_MODES:
        raise ValueError("execution_mode must be formal or trial")
    executed_at = _aware(now or utcnow())
    normalized_cycle = _clean(allocation_cycle_id)
    normalized_actor = _clean(actor) or "manual"
    normalized_transition_key = _clean(transition_key)

    lead = session.get(ClueMasterLead, normalized_lead_key)
    if lead is None:
        raise ValueError("clue master lead was not found")
    if lead.lifecycle_status != "active" or lead.normalized_order_status != "active":
        return AllocationResult(
            lead_key=lead.lead_key,
            status="skipped",
            reason="lead_not_active",
            selected_store_id=None,
            assignment_round_id=None,
        )

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
        return AllocationResult(
            lead_key=lead.lead_key,
            status="headquarters",
            reason=completed_decision.reason,
            selected_store_id=None,
            assignment_round_id=None,
            decision_ids=(completed_decision.decision_id,),
        )

    try:
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
        _project_headquarters(lead, executed_at)
        session.flush()
        return AllocationResult(lead.lead_key, "headquarters", decision.reason, None, None, (decision.decision_id,))

    anchor_reason = _anchor_unavailable_reason(lead)
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
        _project_headquarters(lead, executed_at)
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
        _project_headquarters(lead, executed_at)
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
    stores = session.scalars(select(DimStore).order_by(DimStore.store_id)).all()
    scores = _latest_scores(session, {store.store_id for store in stores})
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

        candidates, reason = _strategy_candidates(
            strategy_type=strategy_type,
            lead=lead,
            sale_store=sale_store,
            stores=stores,
            scores=scores,
            historical_store_ids=historical_store_ids,
            max_distance_km=max_distance_km,
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
                ),
                transition_key=normalized_transition_key,
            )
            decision_ids.append(decision.decision_id)
            continue

        round_no = _next_round_no(session, lead.lead_key, normalized_mode)
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
        )
        snapshot["assignment_round"] = {
            "assignment_round_id": assignment_round_id,
            "round_no": round_no,
            "execution_mode": normalized_mode,
            "allocation_cycle_id": normalized_cycle,
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
        )
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
    _project_headquarters(lead, executed_at)
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
) -> list[AllocationResult]:
    """Explicit batch helper for a caller that has already selected M1 leads."""

    return [
        allocate_lead(
            session,
            lead_key,
            execution_mode=execution_mode,
            allocation_cycle_id=allocation_cycle_id,
            actor=actor,
            now=now,
        )
        for lead_key in lead_keys
    ]


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
    scores: dict[str, StoreScoreSnapshot],
    historical_store_ids: set[str],
    max_distance_km: float | None,
) -> tuple[list[dict[str, Any]], str | None]:
    stores_by_id = {store.store_id: store for store in stores}
    if strategy_type == "sales_store_priority":
        if sale_store["status"] != "resolved":
            return [], str(sale_store["status"])
        sale_store_id = sale_store.get("store_id")
        store = stores_by_id.get(sale_store_id)
        if store is None:
            return [
                _unknown_store_candidate(
                    store_id=sale_store_id,
                    reason="sale_store_unmapped",
                    used_for_ranking=False,
                )
            ], "sale_store_unmapped"
        candidate = _candidate_record(
            store,
            lead=lead,
            score=scores.get(store.store_id),
            require_same_city=False,
            exclude_history=True,
            historical_store_ids=historical_store_ids,
            max_distance_km=max_distance_km,
            used_for_ranking=False,
        )
        if not candidate["eligible"]:
            if "distance_exceeds_max" in candidate["exclusion_reasons"]:
                return [candidate], "sale_store_over_distance"
            if "historically_self_owned" in candidate["exclusion_reasons"]:
                return [candidate], "sale_store_previously_assigned"
            return [candidate], "sale_store_ineligible"
        candidate["rank"] = 1
        return [candidate], None

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
        )
        for store in stores
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
    return candidates, None if ranked else "no_candidate"


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
) -> dict[str, Any]:
    reasons = _candidate_eligibility_reasons(store)
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
        "snapshot_date": snapshot.snapshot_date.isoformat() if snapshot.snapshot_date else None,
        "computed_at": _iso_datetime(snapshot.computed_at),
        "composite_score": float(snapshot.composite_score),
        "conversion_rate": float(snapshot.conversion_rate),
        "conversion_value_source": snapshot.conversion_value_source,
        "follow_24h_rate": float(snapshot.follow_24h_rate),
        "follow_24h_value_source": snapshot.follow_24h_value_source,
        "store_weight": float(snapshot.store_weight),
    }


def _latest_scores(session: Session, store_ids: set[str]) -> dict[str, StoreScoreSnapshot]:
    if not store_ids:
        return {}
    rows = session.scalars(
        select(StoreScoreSnapshot)
        .where(StoreScoreSnapshot.store_id.in_(store_ids))
        .order_by(StoreScoreSnapshot.store_id, StoreScoreSnapshot.computed_at.desc(), StoreScoreSnapshot.snapshot_id.desc())
    ).all()
    latest: dict[str, StoreScoreSnapshot] = {}
    for row in rows:
        latest.setdefault(row.store_id, row)
    return latest


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
    binding: ClueLeadRuleVersionBinding,
    decision: ClueAllocationDecision,
    selected: dict[str, Any],
    executed_at: datetime,
) -> ClueAssignmentRound:
    if not decision.assignment_round_id or decision.round_no is None:
        raise RuntimeError("selected allocation decision must contain its round identity")
    existing = session.get(ClueAssignmentRound, decision.assignment_round_id)
    if existing is not None:
        return existing

    rule_snapshot = dict(binding.rule_version_snapshot or {})
    first_follow_up_sla_hours = _positive_int(rule_snapshot.get("first_follow_up_sla_hours"), 24)
    protection_days = _positive_int(rule_snapshot.get("protection_days"), 7)
    round_row = ClueAssignmentRound(
        assignment_round_id=decision.assignment_round_id,
        order_id=lead.order_id or "",
        lead_key=lead.lead_key,
        rule_version_id=binding.rule_version_id,
        strategy_type=decision.strategy_type,
        allocation_decision_id=decision.decision_id,
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
        auto_expiry_enabled=bool(rule_snapshot.get("auto_expiry_enabled", True)),
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
        winner = session.get(ClueAssignmentRound, decision.assignment_round_id)
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
    lead.pool_location = "store_follow_up_pool"
    lead.allocation_state = "assigned"
    lead.current_assignment_round_id = round_row.assignment_round_id
    lead.allocation_cycle_id = allocation_cycle_id
    lead.ended_without_assignment = False
    lead.updated_at = executed_at

    center_order = session.get(ClueCenterOrder, round_row.order_id)
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
        session.get(ClueAssignmentRound, center_order.current_assignment_round_id)
        if center_order.current_assignment_round_id
        else None
    )
    if (
        existing_center_round is not None
        and existing_center_round.execution_mode in SELF_OWNED_EXECUTION_MODES
        and existing_center_round.lead_key != lead.lead_key
    ):
        # The legacy compatibility projection is still order-grain. Do not let
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


def _project_headquarters(lead: ClueMasterLead, executed_at: datetime) -> None:
    lead.pool_location = "headquarters_pool"
    lead.allocation_state = "headquarters"
    lead.current_assignment_round_id = None
    lead.ended_without_assignment = False
    lead.updated_at = executed_at


def _current_self_owned_round(session: Session, lead: ClueMasterLead) -> ClueAssignmentRound | None:
    if not lead.current_assignment_round_id:
        return None
    row = session.get(ClueAssignmentRound, lead.current_assignment_round_id)
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
