"""Canonical received-task metrics and actual-time verification attribution.

All readers aggregate the integer facts returned here. Reporting periods and
permissions select facts at the caller; neither can change a verification's
original task attribution or its first effective self-store business date.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.clue_followup_metrics import (
    AssignmentRoundEvidence,
    ClueFollowUpEvidence,
    FollowUpEvidence,
    TerminalEvidence,
    load_clue_followup_evidence,
)
from apps.api.dy_api.clue_product_scope import scope_predicate, validate_product_scope
from apps.api.dy_api.clue_task_metrics_sources import (
    EffectiveVerification,
    OrderProductClassification,
    batches,
    jingcheng_order_predicate,
    load_effective_verifications,
    load_order_product_classifications,
    utc,
)
from apps.api.dy_api.models import ClueAssignmentRound, ClueMasterLead


TASK_METRIC_VERSION = "clue-task-v1-actual-time-attribution"
SHANGHAI = ZoneInfo("Asia/Shanghai")
FOLLOW_WINDOW = timedelta(hours=24)
MANUAL_FOLLOW_RESULTS = frozenset({
    "appointment", "further_follow_up", "unreachable", "lost", "request_store_change",
})
ACTIVE_STATUSES = frozenset({"active_unfollowed", "active_followed"})
PENDING_HANDOFF_STATUSES = frozenset({"expired_pending_reassign", "failed_pending_reassign"})
CLUE_TASK_METRIC_DEFINITIONS = {
    "follow_24h_rate": "正式接收任务后固定24小时内首次有效人工提交/共用跟进分母；核销不自动计跟进",
    "follow_any_rate": "本轮有效期间有过有效人工提交/共用跟进分母；每任务最多一次",
    "follow_denominator": "正式接收任务；24小时内全额退款或订单失效且结束前无有效提交时排除；提前核销仍保留",
    "verification_rate": "按实际核销时间归属本店有效任务或整体关闭后补计原承接任务/本店正式接收任务",
    "self_store_verification_count": "订单+实际核销店全期去重，归该店首次有效核销的中国业务日期；包含没有任务的订单",
}


@dataclass(frozen=True)
class VerificationAttribution:
    """Explain one effective coupon verification for a shown task."""

    verify_id: str
    verified_at: datetime
    verified_store_id: str | None
    verified_store_name: str | None
    assignment_round_id: str
    effective_assignment_round_id: str | None
    credited_assignment_round_id: str | None
    is_cross_store: bool
    is_after_close: bool
    had_valid_follow_before_verify: bool
    counts_for_store_verification_rate: bool
    is_back_credit: bool

    def as_dict(self) -> dict[str, object]:
        """Return the JSON-facing round-detail contract."""
        return asdict(self)


@dataclass(frozen=True)
class ClueTaskMetric:
    """One formally received task, with independent metric denominators."""

    assignment_round_id: str
    order_id: str
    store_id: str
    assigned_at: datetime
    product_type: str | None
    is_jingcheng: bool
    follow_24h_numerator: int
    follow_any_numerator: int
    follow_denominator: int
    verification_numerator: int
    verification_denominator: int
    verification_facts: tuple[VerificationAttribution, ...] = ()
    reason_code: str = "active_matured"
    deadline: datetime | None = None
    terminal_kind: str | None = None
    terminal_at: datetime | None = None
    under_observation: bool = False
    follow_record_ids: tuple[str, ...] = ()
    follow_any_record_ids: tuple[str, ...] = ()
    closed_at: datetime | None = None

    @property
    def product_scope(self) -> str:
        return "jingcheng" if self.is_jingcheng else "byd"

    @property
    def numerator(self) -> int:
        return self.follow_24h_numerator

    @property
    def denominator(self) -> int:
        return self.follow_denominator

    @property
    def follow_24h_denominator(self) -> int:
        return self.follow_denominator

    @property
    def follow_any_denominator(self) -> int:
        return self.follow_denominator

    @property
    def follow_24h_rate(self) -> float | None:
        return self.follow_24h_numerator / self.follow_denominator if self.follow_denominator else None

    @property
    def follow_any_rate(self) -> float | None:
        return self.follow_any_numerator / self.follow_denominator if self.follow_denominator else None

    @property
    def verification_rate(self) -> float | None:
        return self.verification_numerator / self.verification_denominator if self.verification_denominator else None

    def as_dict(self) -> dict[str, object]:
        """Return counts plus the public verification explanation."""
        return asdict(self)


@dataclass(frozen=True)
class SelfStoreVerification:
    """One order/store's globally first currently effective verification."""

    store_id: str
    order_id: str
    verify_id: str
    verified_at: datetime
    business_date: date
    product_type: str | None = None
    is_jingcheng: bool = False

    @property
    def product_scope(self) -> str:
        return "jingcheng" if self.is_jingcheng else "byd"


@dataclass(frozen=True)
class StoreTaskTotals:
    """Raw task totals consumed by the allocation score's 70/30 formula."""

    conversion_numerator: int = 0
    conversion_denominator: int = 0
    follow_24h_numerator: int = 0
    follow_24h_denominator: int = 0
    follow_any_numerator: int = 0


@dataclass(frozen=True)
class _LeadClose:
    at: datetime
    reason: str | None
    lead_key: str | None


def _first_per_store(events: Iterable[EffectiveVerification]) -> tuple[EffectiveVerification, ...]:
    chosen: dict[str | None, EffectiveVerification] = {}
    for event in sorted(events, key=lambda item: (item.verified_at, item.verify_id)):
        chosen.setdefault(event.store_id, event)
    return tuple(chosen.values())


def _minimum(*values: datetime | None) -> datetime | None:
    known = [value for value in values if value is not None]
    return min(known) if known else None


def _verification_close(round_value: AssignmentRoundEvidence) -> bool:
    return "verif" in str(round_value.terminal_reason or "").lower() or "verif" in str(round_value.round_status or "").lower()


def _valid_follows(
    round_value: AssignmentRoundEvidence,
    records: Iterable[FollowUpEvidence],
    *,
    cutoff: datetime,
    end_at: datetime | None,
    next_at: datetime | None,
    terminal_at: datetime | None,
) -> tuple[FollowUpEvidence, ...]:
    valid: dict[str, FollowUpEvidence] = {}
    for record in records:
        at = utc(record.created_at)
        if (record.deleted_at is not None or at is None or record.follow_result not in MANUAL_FOLLOW_RESULTS
                or record.order_id != round_value.order_id
                or record.assignment_round_id != round_value.assignment_round_id
                or record.assigned_store_id != round_value.assigned_store_id
                or at < round_value.assigned_at or at > cutoff):
            continue
        if terminal_at is not None and at >= terminal_at:
            continue
        if next_at is not None and at >= next_at:
            continue
        if end_at is not None and at >= end_at:
            # The action that actually closes a task is itself a valid
            # submission. Later immutable records cannot extend its period.
            closes_task = (
                at == end_at and at == round_value.closed_at
                and record.follow_result in {"lost", "request_store_change"}
            )
            if not closes_task:
                continue
        valid.setdefault(record.follow_up_record_id, record)
    return tuple(sorted(valid.values(), key=lambda item: (item.created_at, item.follow_up_record_id)))


def _evaluate_order(
    evidence: ClueFollowUpEvidence,
    *,
    events: tuple[EffectiveVerification, ...],
    classification: OrderProductClassification,
    lead_closes: tuple[_LeadClose, ...],
    cutoff: datetime,
) -> dict[str, ClueTaskMetric]:
    rounds = sorted((row for row in evidence.rounds if (
        row.execution_mode == "formal" and row.assigned_at is not None
        and row.assigned_store_id and row.assigned_at <= cutoff
    )), key=lambda row: (row.assigned_at, row.round_no, row.assignment_round_id))
    if not rounds:
        return {}
    # Conversion attribution evaluates every effective coupon independently.
    # Only self-store volume deduplicates an order/store to its first date:
    # a later coupon may independently qualify for post-close back-credit.
    events = tuple(sorted(events, key=lambda item: (item.verified_at, item.verify_id)))
    first_verify_at = min((event.verified_at for event in events), default=None)
    nonverify = evidence.non_verification_terminal
    terminal = evidence.terminal
    # Source terminal projections may prove a closed state while omitting its
    # business time. They must not invent an early-refund exclusion.
    nonverify_at = nonverify.terminal_at if nonverify.kind in {"refunded", "closed"} else None
    terminal_candidates = [(at, kind) for at, kind in (
        (first_verify_at, "verified"), (nonverify_at, nonverify.kind),
        (terminal.terminal_at, terminal.kind),
    ) if at is not None and at <= cutoff]
    if terminal_candidates:
        terminal_at, terminal_kind = min(terminal_candidates, key=lambda item: (item[0], item[1] != "verified"))
    else:
        terminal_at, terminal_kind = None, terminal.kind
    lead_close_at = min((item.at for item in lead_closes), default=None)
    overall_close_at = _minimum(lead_close_at, terminal_at)
    last = rounds[-1]
    if (last.round_status not in ACTIVE_STATUSES | PENDING_HANDOFF_STATUSES
            and last.closed_at is not None):
        overall_close_at = _minimum(overall_close_at, last.closed_at)
    next_times = {
        row.assignment_round_id: rounds[index + 1].assigned_at if index + 1 < len(rounds) else None
        for index, row in enumerate(rounds)
    }
    physical_ends: dict[str, datetime | None] = {}
    ends: dict[str, datetime | None] = {}
    valid_by_round: dict[str, tuple[FollowUpEvidence, ...]] = {}
    for row in rounds:
        physical_ends[row.assignment_round_id] = _minimum(row.closed_at, row.reassigned_at, next_times[row.assignment_round_id])
        ends[row.assignment_round_id] = _minimum(physical_ends[row.assignment_round_id], overall_close_at)
        valid_by_round[row.assignment_round_id] = _valid_follows(
            row, evidence.follow_ups_for(row.assignment_round_id), cutoff=cutoff,
            end_at=ends[row.assignment_round_id], next_at=next_times[row.assignment_round_id],
            terminal_at=terminal_at,
        )

    attributed: list[tuple[EffectiveVerification, str | None, str | None, bool, bool]] = []
    for event in events:
        at = event.verified_at
        # An actual verification at the terminal instant closes the task that
        # was still valid then; a next assignment at that instant owns it.
        closes_now = at == first_verify_at and at == overall_close_at and (
            nonverify_at is None or nonverify_at >= at
        )
        is_after_close = overall_close_at is not None and at > overall_close_at
        active = None
        for row in reversed(rounds):
            if row.assigned_at > at:
                continue
            end = physical_ends[row.assignment_round_id]
            if end is not None and at >= end:
                equals_verify_close = (
                    at == end and closes_now and _verification_close(row)
                    and next_times[row.assignment_round_id] != at and row.reassigned_at != at
                )
                if not equals_verify_close:
                    continue
            if overall_close_at is not None and (at > overall_close_at or (at == overall_close_at and not closes_now)):
                continue
            if (end is None and row.round_status not in ACTIVE_STATUSES | PENDING_HANDOFF_STATUSES
                    and not _verification_close(row)):
                # A historical closed status with no reliable timestamp is
                # insufficient evidence that a future event was in-period.
                continue
            active = row
            break
        credit = active if active and active.assigned_store_id == event.store_id else None
        is_back_credit = False
        if active is None and is_after_close and event.store_id:
            prior = [row for row in rounds if row.assigned_store_id == event.store_id
                     and row.assigned_at <= overall_close_at]
            if prior:
                credit = prior[-1]
                is_back_credit = True
        attributed.append((event, active.assignment_round_id if active else None,
                           credit.assignment_round_id if credit else None,
                           is_after_close, is_back_credit))

    result: dict[str, ClueTaskMetric] = {}
    for row in rounds:
        row_id = row.assignment_round_id
        follows = valid_by_round[row_id]
        deadline = row.assigned_at + FOLLOW_WINDOW
        follows_24h = tuple(item for item in follows if item.created_at <= deadline)
        early_invalid = (
            terminal_kind in {"refunded", "closed"} and terminal_at is not None
            and terminal_at <= deadline and not follows
        )
        denominator = 0 if early_invalid else 1
        detail = tuple(VerificationAttribution(
            verify_id=event.verify_id, verified_at=event.verified_at,
            verified_store_id=event.store_id, verified_store_name=event.store_name,
            assignment_round_id=row_id, effective_assignment_round_id=active_id,
            credited_assignment_round_id=credit_id,
            is_cross_store=event.store_id is not None and event.store_id != row.assigned_store_id,
            is_after_close=after_close,
            had_valid_follow_before_verify=any(item.created_at < event.verified_at for item in follows),
            counts_for_store_verification_rate=credit_id == row_id,
            is_back_credit=back_credit,
        ) for event, active_id, credit_id, after_close, back_credit in attributed
            if event.verified_at >= row.assigned_at)
        closed_by_cutoff = ends[row_id] is not None and ends[row_id] <= cutoff
        under_observation = not closed_by_cutoff and cutoff < deadline
        reason = (
            "early_invalid_without_follow" if early_invalid
            else "terminal_time_unknown" if terminal_kind and terminal_at is None
            else "terminal_before_assignment" if terminal_at is not None and terminal_at < row.assigned_at
            else "task_closed" if closed_by_cutoff
            else "active_under_observation" if under_observation else "active_matured"
        )
        result[row_id] = ClueTaskMetric(
            assignment_round_id=row_id, order_id=row.order_id, store_id=row.assigned_store_id,
            assigned_at=row.assigned_at, product_type=classification.product_type,
            is_jingcheng=classification.is_jingcheng,
            follow_24h_numerator=int(bool(denominator and follows_24h)),
            follow_any_numerator=int(bool(denominator and follows)), follow_denominator=denominator,
            verification_numerator=int(any(item.counts_for_store_verification_rate for item in detail)),
            verification_denominator=1, verification_facts=detail, reason_code=reason,
            deadline=deadline, terminal_kind=terminal_kind, terminal_at=terminal_at,
            under_observation=under_observation,
            follow_record_ids=tuple(item.follow_up_record_id for item in follows_24h),
            follow_any_record_ids=tuple(item.follow_up_record_id for item in follows),
            closed_at=ends[row_id] if closed_by_cutoff else None,
        )
    return result


def load_clue_task_facts(
    session: Session,
    order_ids: Iterable[str],
    *,
    observed_through: datetime | None = None,
) -> dict[str, ClueTaskMetric]:
    """Load canonical facts for every received formal task of the given orders.

    History is loaded before callers select assignment dates or stores. This
    function never mutates rounds, follow-up records or order projections.
    """
    requested = tuple(value for batch in batches(order_ids) for value in batch)
    cutoff = utc(observed_through) or datetime.now(timezone.utc)
    if not requested:
        return {}
    evidence = load_clue_followup_evidence(session, requested, observed_through=cutoff)
    products = load_order_product_classifications(session, requested)
    verifications = load_effective_verifications(session, requested, observed_through=cutoff)
    closes: defaultdict[str, list[_LeadClose]] = defaultdict(list)
    for batch in batches(requested):
        for row in session.execute(select(
            ClueMasterLead.order_id, ClueMasterLead.lead_key,
            ClueMasterLead.closed_at, ClueMasterLead.closed_reason,
        ).where(ClueMasterLead.order_id.in_(batch), ClueMasterLead.closed_at <= cutoff)):
            closes[str(row.order_id)].append(_LeadClose(utc(row.closed_at), row.closed_reason, row.lead_key))
    result: dict[str, ClueTaskMetric] = {}
    for order_id in requested:
        result.update(_evaluate_order(
            evidence[order_id], events=verifications.get(order_id, ()),
            classification=products[order_id], lead_closes=tuple(closes[order_id]), cutoff=cutoff,
        ))
    return result


def load_self_store_verifications(
    session: Session,
    order_ids: Iterable[str],
    *,
    observed_through: datetime | None = None,
) -> tuple[SelfStoreVerification, ...]:
    """Return first effective order/store verifications before date filtering.

    Business dates are China dates, even if the actual timestamp is the
    previous UTC day. Trial tasks do not contribute evidence to this reader;
    an actual source verification counts with or without a formal task.
    """
    requested = tuple(value for batch in batches(order_ids) for value in batch)
    cutoff = utc(observed_through) or datetime.now(timezone.utc)
    products = load_order_product_classifications(session, requested)
    events = load_effective_verifications(session, requested, observed_through=cutoff)
    result = []
    for order_id in requested:
        product = products[order_id]
        for event in _first_per_store(events.get(order_id, ())):
            if not event.store_id:
                continue
            result.append(SelfStoreVerification(
                store_id=event.store_id, order_id=order_id, verify_id=event.verify_id,
                verified_at=event.verified_at, business_date=event.verified_at.astimezone(SHANGHAI).date(),
                product_type=product.product_type, is_jingcheng=product.is_jingcheng,
            ))
    return tuple(sorted(result, key=lambda item: (item.verified_at, item.store_id, item.order_id)))


def load_store_task_totals(
    session: Session,
    store_ids: Iterable[str],
    window_start: datetime,
    window_end: datetime,
    *,
    product_scope: str = "jingcheng",
    observed_through: datetime | None = None,
) -> dict[str, StoreTaskTotals]:
    """Aggregate received-task cohorts for allocation, using [start, end)."""
    validate_product_scope(product_scope)
    stores = {value for batch in batches(store_ids) for value in batch}
    start, end = utc(window_start), utc(window_end)
    cutoff = utc(observed_through) or datetime.now(timezone.utc)
    if start >= end:
        raise ValueError("task metric window must end after its start")
    order_ids: set[str] = set()
    for batch in batches(stores):
        order_ids.update(session.scalars(select(ClueAssignmentRound.order_id).where(
            ClueAssignmentRound.assigned_store_id.in_(batch),
            ClueAssignmentRound.execution_mode == "formal",
            ClueAssignmentRound.assigned_at >= start, ClueAssignmentRound.assigned_at < end,
            ClueAssignmentRound.assigned_at <= cutoff,
            scope_predicate(product_scope, jingcheng_order_predicate(ClueAssignmentRound.order_id)),
        )).all())
    counters = {store_id: [0, 0, 0, 0, 0] for store_id in stores}
    for fact in load_clue_task_facts(session, order_ids, observed_through=cutoff).values():
        if (fact.store_id not in stores or not start <= fact.assigned_at < end
                or product_scope != "all" and fact.product_scope != product_scope):
            continue
        counts = counters[fact.store_id]
        for index, value in enumerate((fact.verification_numerator, fact.verification_denominator,
                                       fact.follow_24h_numerator, fact.follow_denominator,
                                       fact.follow_any_numerator)):
            counts[index] += value
    return {store_id: StoreTaskTotals(*counts) for store_id, counts in counters.items()}


__all__ = [
    "TASK_METRIC_VERSION", "CLUE_TASK_METRIC_DEFINITIONS", "ClueTaskMetric",
    "VerificationAttribution", "SelfStoreVerification", "StoreTaskTotals",
    "load_clue_task_facts", "load_self_store_verifications", "load_store_task_totals",
]
