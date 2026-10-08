"""Shared, terminal-aware clue follow-up metrics.

The clue allocation and ranking paths used to carry slightly different copies
of the 24-hour calculation.  This module keeps the business rule in two
layers:

* :func:`load_clue_followup_evidence` performs one bounded evidence load for a
  set of order IDs and keeps observation-cutoff handling at the source edge.
* :func:`evaluate_clue_followup_round` is pure.  It only receives immutable
  round/evidence values, which lets the allocation score and both ranking
  readers share exactly the same boundary behaviour.

The loader deliberately does not apply organization or product filters.  The
caller owns those scopes and passes the already-authorized order IDs.  That
keeps attribution and access policy unchanged while avoiding a second product
or store mapping implementation here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Iterable, Literal, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueFollowUpRecord,
    DouyinRefundEvent,
    RawDouyinClue,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinRefundRecord,
    RawDouyinVerifyRecord,
    SettlementOrderDetail,
)
from apps.worker.order_status import normalize_coupon_status, resolve_clue_order_status


FOLLOW_UP_METRIC_VERSION = "clue-followup-v2-assigned-terminal-aware"
FOLLOW_UP_WINDOW = timedelta(hours=24)
EVIDENCE_QUERY_BATCH_SIZE = 500

VERIFY_SUCCESS_STATUSES = frozenset(
    {"1", "401", "success", "verified", "已核销", "used", "fulfilled", "transaction_success"}
)
REFUND_COMPLETE_STATUS = 2
FULL_REFUND_TYPES = frozenset({"2", "full", "full_refund", "all"})
TERMINAL_KINDS = frozenset({"verified", "refunded", "closed"})

CLUE_FOLLOWUP_METRIC_DEFINITIONS: dict[str, str] = {
    "follow_24h_rate": (
        "正式分配轮次中，按assigned_at起算；未终止轮次立即计入分母，"
        "终止超过24小时计入分母；分子为分配后24小时内、终止前的同轮次同门店未删除跟进"
    ),
    "follow_any_rate": (
        "正式分配轮次中，分配后且终止前存在同轮次同门店未删除跟进的轮次占比；"
        "该辅助指标同样遵守观测截止时间"
    ),
    "terminal_evidence": (
        "核销、全量退款或关闭证据的业务发生时间与来源观测时间分离；"
        "部分或待处理退款不构成退款终态"
    ),
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: object | None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _normal_status(value: object | None) -> str:
    return (_text(value) or "").lower().replace("-", "_")


def _first_time(payload: Mapping[str, Any] | None, *keys: str) -> datetime | None:
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            value = value.get("value") or value.get("time") or value.get("timestamp")
        if isinstance(value, datetime):
            return _aware(value)
        if value in (None, "", 0, "0"):
            continue
        if isinstance(value, (int, float)):
            # Douyin payloads use both seconds and milliseconds for timestamps.
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000
            try:
                return datetime.fromtimestamp(numeric, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                continue
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            return _aware(datetime.fromisoformat(raw))
        except ValueError:
            continue
    return None


def _max_time(*values: datetime | None) -> datetime | None:
    candidates = [value for value in (_aware(item) for item in values) if value is not None]
    return max(candidates) if candidates else None


REFUND_TIME_KEYS = frozenset(
    {
        "refund_completed_at",
        "completed_at",
        "finish_time",
        "refund_done_at",
        "complete_time",
        "refund_time",
        "coupon_refund_time",
    }
)


def _refund_times_from_payload(payload: Mapping[str, Any] | None) -> tuple[datetime, ...]:
    """Extract business refund times from order/clue certificate payloads."""

    found: list[datetime] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key).lower() in REFUND_TIME_KEYS:
                    parsed = _first_time({str(key): child}, str(key))
                    if parsed is not None:
                        found.append(parsed)
                elif isinstance(child, (Mapping, list, tuple)):
                    visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(payload)
    return tuple(found)


@dataclass(frozen=True)
class TerminalEvidence:
    """The effective terminal event for one order at one observation cutoff."""

    kind: Literal["verified", "refunded", "closed"] | None
    terminal_at: datetime | None
    observed_at: datetime | None
    source: str | None = None
    evidence_ids: tuple[str, ...] = ()

    @property
    def is_terminal(self) -> bool:
        return self.kind in TERMINAL_KINDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "terminal_at": self.terminal_at,
            "observed_at": self.observed_at,
            "source": self.source,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class AssignmentRoundEvidence:
    assignment_round_id: str
    order_id: str
    round_no: int
    assigned_store_id: str | None
    assigned_at: datetime | None
    execution_mode: str = "formal"
    verified_store_id: str | None = None
    verified_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Any) -> "AssignmentRoundEvidence":
        return cls(
            assignment_round_id=str(getattr(row, "assignment_round_id", "")),
            order_id=str(getattr(row, "order_id", "")),
            round_no=int(getattr(row, "round_no", 0) or 0),
            assigned_store_id=_text(getattr(row, "assigned_store_id", None)),
            assigned_at=_aware(getattr(row, "assigned_at", None)),
            execution_mode=_text(getattr(row, "execution_mode", None)) or "formal",
            verified_store_id=_text(getattr(row, "verified_store_id", None)),
            verified_at=_aware(getattr(row, "verified_at", None)),
            updated_at=_aware(getattr(row, "updated_at", None)),
        )


@dataclass(frozen=True)
class FollowUpEvidence:
    follow_up_record_id: str
    order_id: str
    assignment_round_id: str
    assigned_store_id: str | None
    created_at: datetime | None
    deleted_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Any) -> "FollowUpEvidence":
        return cls(
            follow_up_record_id=str(getattr(row, "follow_up_record_id", "")),
            order_id=str(getattr(row, "order_id", "")),
            assignment_round_id=str(getattr(row, "assignment_round_id", "")),
            assigned_store_id=_text(getattr(row, "assigned_store_id", None)),
            created_at=_aware(getattr(row, "created_at", None)),
            deleted_at=_aware(getattr(row, "deleted_at", None)),
        )


@dataclass(frozen=True)
class VerificationEvidence:
    verify_id: str
    order_id: str
    verified_at: datetime | None
    poi_id: str | None = None
    store_id: str | None = None
    cancel_at: datetime | None = None
    observed_at: datetime | None = None
    source: str = "raw_verify"

    @property
    def is_successful(self) -> bool:
        return self.verified_at is not None


@dataclass(frozen=True)
class ClueFollowUpEvidence:
    """Bulk-loaded evidence for one order.

    ``rounds`` can contain historical rounds outside a reporting period.  A
    caller selects the rounds it owns for scoring; all rounds are retained here
    so terminal attribution can use the complete order history.
    """

    order_id: str
    rounds: tuple[AssignmentRoundEvidence, ...] = ()
    follow_ups_by_round: Mapping[str, tuple[FollowUpEvidence, ...]] = field(default_factory=dict)
    verifications: tuple[VerificationEvidence, ...] = ()
    terminal: TerminalEvidence = field(default_factory=lambda: TerminalEvidence(None, None, None))
    observed_through: datetime | None = None

    def follow_ups_for(self, assignment_round_id: str) -> tuple[FollowUpEvidence, ...]:
        return tuple(self.follow_ups_by_round.get(assignment_round_id, ()))


@dataclass(frozen=True)
class FollowUpMetric:
    assignment_round_id: str
    order_id: str
    numerator: int
    denominator: int
    follow_any_numerator: int
    follow_any_denominator: int
    reason_code: str
    deadline: datetime | None
    terminal_kind: str | None
    terminal_at: datetime | None
    follow_record_ids: tuple[str, ...] = ()
    follow_any_record_ids: tuple[str, ...] = ()
    under_observation: bool = False

    @property
    def follow_24h_rate(self) -> float | None:
        return self.numerator / self.denominator if self.denominator else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "assignment_round_id": self.assignment_round_id,
            "order_id": self.order_id,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "follow_any_numerator": self.follow_any_numerator,
            "follow_any_denominator": self.follow_any_denominator,
            "reason_code": self.reason_code,
            "deadline": self.deadline,
            "terminal_kind": self.terminal_kind,
            "terminal_at": self.terminal_at,
            "follow_record_ids": list(self.follow_record_ids),
            "follow_any_record_ids": list(self.follow_any_record_ids),
            "under_observation": self.under_observation,
        }


def _terminal_visible_at(terminal: TerminalEvidence, cutoff: datetime) -> TerminalEvidence:
    """Ignore terminal evidence that arrived after the requested cutoff."""

    observed_at = _aware(terminal.observed_at)
    if observed_at is not None and observed_at > cutoff:
        return TerminalEvidence(None, None, observed_at, terminal.source, terminal.evidence_ids)
    terminal_at = _aware(terminal.terminal_at)
    if terminal_at is not None and terminal_at > cutoff:
        return TerminalEvidence(None, None, observed_at, terminal.source, terminal.evidence_ids)
    return TerminalEvidence(terminal.kind, terminal_at, observed_at, terminal.source, terminal.evidence_ids)


def evaluate_clue_followup_round(
    round_row: AssignmentRoundEvidence | Any,
    *,
    follow_ups: Iterable[FollowUpEvidence | Any] = (),
    terminal: TerminalEvidence | None = None,
    observed_through: datetime | None = None,
) -> FollowUpMetric:
    """Evaluate one round without reading the database.

    Assignment time is always ``assigned_at``.  The historical KPI-only
    ``metric_follow_24h_start_at`` is intentionally not consulted.
    """

    round_value = (
        round_row if isinstance(round_row, AssignmentRoundEvidence) else AssignmentRoundEvidence.from_row(round_row)
    )
    cutoff = _aware(observed_through) or _now_utc()
    assigned_at = _aware(round_value.assigned_at)
    deadline = assigned_at + FOLLOW_UP_WINDOW if assigned_at is not None else None
    assignment_round_id = round_value.assignment_round_id
    order_id = round_value.order_id
    empty_kwargs = dict(
        assignment_round_id=assignment_round_id,
        order_id=order_id,
        deadline=deadline,
        terminal_kind=terminal.kind if terminal else None,
        terminal_at=_aware(terminal.terminal_at) if terminal else None,
    )
    if round_value.execution_mode != "formal":
        return FollowUpMetric(
            assignment_round_id=assignment_round_id,
            order_id=order_id,
            numerator=0,
            denominator=0,
            follow_any_numerator=0,
            follow_any_denominator=0,
            reason_code="non_formal_round",
            **{key: value for key, value in empty_kwargs.items() if key not in {"assignment_round_id", "order_id"}},
        )
    if assigned_at is None:
        return FollowUpMetric(
            assignment_round_id=assignment_round_id,
            order_id=order_id,
            numerator=0,
            denominator=0,
            follow_any_numerator=0,
            follow_any_denominator=0,
            reason_code="unassigned_round",
            **{key: value for key, value in empty_kwargs.items() if key not in {"assignment_round_id", "order_id"}},
        )
    if assigned_at > cutoff:
        # A round observed after the requested cutoff has no denominator yet;
        # this keeps replayed/future assignment rows out of historical reads.
        return FollowUpMetric(
            assignment_round_id=assignment_round_id,
            order_id=order_id,
            numerator=0,
            denominator=0,
            follow_any_numerator=0,
            follow_any_denominator=0,
            reason_code="assignment_after_observation_cutoff",
            **{key: value for key, value in empty_kwargs.items() if key not in {"assignment_round_id", "order_id"}},
        )

    visible_terminal = _terminal_visible_at(
        terminal or TerminalEvidence(None, None, None), cutoff
    )
    terminal_at = visible_terminal.terminal_at
    terminal_kind = visible_terminal.kind
    if terminal_at is not None and terminal_at <= assigned_at:
        return FollowUpMetric(
            assignment_round_id,
            order_id,
            0,
            0,
            0,
            0,
            "terminal_before_assignment",
            deadline,
            terminal_kind,
            terminal_at,
        )

    valid_any: list[str] = []
    valid_window: list[str] = []
    seen: set[str] = set()
    for item in follow_ups:
        evidence = item if isinstance(item, FollowUpEvidence) else FollowUpEvidence.from_row(item)
        if evidence.follow_up_record_id in seen:
            continue
        seen.add(evidence.follow_up_record_id)
        created_at = _aware(evidence.created_at)
        if evidence.deleted_at is not None or created_at is None:
            continue
        if evidence.order_id != order_id or evidence.assignment_round_id != assignment_round_id:
            continue
        if evidence.assigned_store_id != round_value.assigned_store_id:
            continue
        if created_at < assigned_at or created_at > cutoff:
            continue
        if terminal_at is not None and created_at >= terminal_at:
            # The terminal boundary is exclusive.  A follow at the exact
            # refund/verification time is post-terminal evidence.
            continue
        valid_any.append(evidence.follow_up_record_id)
        if created_at <= deadline:
            valid_window.append(evidence.follow_up_record_id)

    terminal_within_window = terminal_at is not None and terminal_at <= deadline
    under_observation = terminal_at is None and cutoff < deadline
    if terminal_within_window:
        if terminal_kind == "verified":
            numerator, denominator, reason = 1, 1, "verified_within_24h"
        elif valid_window:
            numerator, denominator, reason = 1, 1, "terminal_within_24h_followed"
        else:
            numerator, denominator, reason = 0, 0, "terminal_within_24h_unfollowed"
    else:
        numerator, denominator = int(bool(valid_window)), 1
        reason = "terminal_after_24h" if terminal_at is not None else "active_under_observation" if under_observation else "active_matured"

    return FollowUpMetric(
        assignment_round_id=assignment_round_id,
        order_id=order_id,
        numerator=numerator,
        denominator=denominator,
        follow_any_numerator=int(bool(valid_any)),
        follow_any_denominator=1,
        reason_code=reason,
        deadline=deadline,
        terminal_kind=terminal_kind,
        terminal_at=terminal_at,
        follow_record_ids=tuple(valid_window),
        follow_any_record_ids=tuple(valid_any),
        under_observation=under_observation,
    )


def _status_observed_at(row: Any) -> datetime | None:
    # Source observation is the cutoff authority.  Local ingestion/update time
    # can be much later when an old payload is replayed or repaired.
    source_observed = _aware(getattr(row, "source_observed_at", None))
    if source_observed is not None:
        return source_observed
    return _max_time(
        getattr(row, "updated_at", None),
        getattr(row, "gmt_modified", None),
        getattr(row, "coupon_updated_at", None),
    )


def _refund_type(row: Any) -> str | None:
    payload = getattr(row, "raw_payload", None)
    value: Any = None
    if isinstance(payload, Mapping):
        value = payload.get("refund_type") or payload.get("type")
        if isinstance(value, Mapping):
            value = value.get("value")
    return _normal_status(value)


def _is_full_completed_refund(row: Any) -> bool:
    if getattr(row, "normalized_refund_status", None) != REFUND_COMPLETE_STATUS:
        return False
    refund_type = _refund_type(row)
    # Older rows can omit refund_type.  They are accepted only when the order
    # or coupon projection separately proves full refund; the caller applies
    # that projection check before using the event timestamp.
    return refund_type in FULL_REFUND_TYPES or refund_type is None


def _terminal_from_rows(
    order_id: str,
    *,
    raw_order: Any | None,
    raw_clues: Sequence[Any],
    coupons: Sequence[Any],
    refunds: Sequence[Any],
    refund_events: Sequence[Any],
    verifications: Sequence[VerificationEvidence],
    observed_through: datetime,
) -> TerminalEvidence:
    raw_order_visible = raw_order is not None and (
        _status_observed_at(raw_order) is None or _status_observed_at(raw_order) <= observed_through
    )
    visible_raw_order = raw_order if raw_order_visible else None
    valid_verifications = [
        item
        for item in verifications
        if item.verified_at is not None
        and item.verified_at <= observed_through
        and (item.observed_at is None or item.observed_at <= observed_through)
    ]
    if valid_verifications:
        earliest = min(valid_verifications, key=lambda item: (item.verified_at or observed_through, item.verify_id))
        observed = _max_time(*(item.observed_at for item in valid_verifications))
        return TerminalEvidence(
            "verified",
            earliest.verified_at,
            observed or earliest.verified_at,
            earliest.source,
            tuple(item.verify_id for item in valid_verifications),
        )

    coupon_statuses: list[str] = []
    coupon_times: list[datetime | None] = []
    coupon_observed: list[datetime | None] = []
    for coupon in coupons:
        normalized = _text(getattr(coupon, "coupon_status_normalized", None))
        coupon_statuses.append(normalized or normalize_coupon_status(
            getattr(coupon, "coupon_status_raw", None) or getattr(coupon, "coupon_status", None)
        ))
        coupon_times.append(
            _max_time(getattr(coupon, "coupon_refund_time", None), getattr(coupon, "latest_refund_at", None))
        )
        coupon_observed.append(_status_observed_at(coupon))

    raw_order_status = getattr(visible_raw_order, "order_status", None) if visible_raw_order is not None else None
    raw_payload = getattr(visible_raw_order, "raw_payload", None) if visible_raw_order is not None else None
    normalized_order = getattr(visible_raw_order, "order_status_normalized", None) if visible_raw_order is not None else None
    # The current order projection is authoritative whenever it carries a
    # status.  Raw clue rows can be stale (for example a historical "closed"
    # row beside a current waiting-use order) and are only a fallback when the
    # order projection has no status at all.
    order_status = str(raw_order_status or normalized_order) if (raw_order_status or normalized_order) else None
    if order_status:
        resolved = resolve_clue_order_status(
            order_status,
            raw_payload,
            normalized_order_status=normalized_order,
            coupon_statuses=coupon_statuses,
        )
    else:
        clue_resolved_statuses: list[str] = []
        for clue in raw_clues:
            clue_status = getattr(clue, "order_status", None)
            if not clue_status:
                continue
            clue_resolved_statuses.append(resolve_clue_order_status(
                str(clue_status),
                getattr(clue, "raw_payload", None),
                coupon_statuses=coupon_statuses,
            ))
        resolved = next(
            (status for status in ("refunded", "closed", "verified") if status in clue_resolved_statuses),
            clue_resolved_statuses[0] if clue_resolved_statuses else None,
        )

    all_coupons_refunded = bool(coupon_statuses) and all(status == "refunded" for status in coupon_statuses)
    all_coupons_closed = bool(coupon_statuses) and all(status == "closed" for status in coupon_statuses)
    full_refund_rows = [
        row
        for row in refunds
        if _is_full_completed_refund(row)
        and (_refund_type(row) in FULL_REFUND_TYPES or resolved == "refunded" or all_coupons_refunded)
    ]
    full_refund_events = [
        row
        for row in refund_events
        if getattr(row, "refund_status", None) == REFUND_COMPLETE_STATUS
        and getattr(row, "refund_type", None) == 2
    ]
    # A completed full-refund projection is itself terminal evidence.  A
    # completed partial/pending record remains non-terminal until the order or
    # coupon projection proves that the full order is refunded.
    refund_terminal = resolved == "refunded" or all_coupons_refunded or bool(full_refund_rows) or bool(full_refund_events)
    closed_terminal = resolved == "closed" or all_coupons_closed

    if refund_terminal:
        refund_times: list[datetime | None] = list(coupon_times)
        refund_observed: list[datetime | None] = list(coupon_observed)
        if visible_raw_order is not None:
            refund_times.extend(_refund_times_from_payload(raw_payload))
        for clue in raw_clues:
            refund_times.extend(_refund_times_from_payload(getattr(clue, "raw_payload", None)))
        for row in full_refund_rows:
            refund_times.append(_max_time(
                getattr(row, "refund_completed_at", None),
                _first_time(getattr(row, "raw_payload", None), "refund_completed_at", "completed_at", "finish_time", "complete_time"),
            ))
            refund_observed.append(_status_observed_at(row))
        for row in full_refund_events:
            refund_times.append(_aware(getattr(row, "occurred_at", None)))
            refund_observed.append(_status_observed_at(row))
        # A complete refund without a business timestamp is terminal for
        # lifecycle purposes, but its metric cannot invent one from ingestion
        # time.  Parent callers can use observed_at for repair bookkeeping.
        terminal_at = _max_time(*refund_times)
        observed_at = _max_time(*refund_observed, getattr(visible_raw_order, "source_observed_at", None) if visible_raw_order is not None else None)
        ids = tuple(
            str(
                getattr(row, "source_record_key", None)
                or getattr(row, "refund_event_id", "")
            )
            for row in [*full_refund_rows, *full_refund_events]
            if (
                getattr(row, "normalized_refund_status", None) == REFUND_COMPLETE_STATUS
                or getattr(row, "refund_status", None) == REFUND_COMPLETE_STATUS
            )
        )
        return TerminalEvidence("refunded", terminal_at, observed_at or terminal_at, "refund", ids)

    if closed_terminal:
        terminal_at = _first_time(raw_payload, "closed_at", "close_time", "cancel_time", "cancelled_at", "canceled_at")
        observed_at = _max_time(
            _status_observed_at(visible_raw_order) if visible_raw_order is not None else None,
            *(_status_observed_at(row) for row in raw_clues),
            *coupon_observed,
        )
        return TerminalEvidence("closed", terminal_at or observed_at, observed_at or terminal_at, "status", ())

    if resolved == "verified":
        # A completed/verified order projection is terminal even when the
        # source omitted a usable business timestamp.  Do not fabricate one;
        # lifecycle callers can still fence on the observed_at value.
        verified_at = _first_time(
            raw_payload,
            "verified_at",
            "verify_time",
            "used_at",
            "completed_at",
            "finish_time",
        )
        observed_at = _max_time(
            _status_observed_at(visible_raw_order) if visible_raw_order is not None else None,
            *(_status_observed_at(row) for row in raw_clues),
            *coupon_observed,
        )
        return TerminalEvidence("verified", verified_at, observed_at or verified_at, "order", ())

    return TerminalEvidence(None, None, None)


def _batch(values: Iterable[str]) -> list[tuple[str, ...]]:
    ordered = tuple(sorted({str(value) for value in values if _text(value)}))
    return [ordered[offset : offset + EVIDENCE_QUERY_BATCH_SIZE] for offset in range(0, len(ordered), EVIDENCE_QUERY_BATCH_SIZE)]


def load_clue_followup_evidence(
    session: Session,
    order_ids: Iterable[str],
    *,
    observed_through: datetime | None = None,
    include_raw_clues: bool = True,
) -> dict[str, ClueFollowUpEvidence]:
    """Load rounds, follows, verification and terminal evidence in batches.

    Source records observed after ``observed_through`` are excluded.  The
    returned dictionary contains every requested order, including orders with
    no rounds, so callers can distinguish empty evidence from a missing key.
    """

    requested = {str(value) for value in order_ids if _text(value)}
    cutoff = _aware(observed_through) or _now_utc()
    if not requested:
        return {}
    rounds_by_order: defaultdict[str, list[AssignmentRoundEvidence]] = defaultdict(list)
    follows_by_round: defaultdict[str, list[FollowUpEvidence]] = defaultdict(list)
    raw_orders: dict[str, Any] = {}
    raw_clues_by_order: defaultdict[str, list[Any]] = defaultdict(list)
    coupons_by_order: defaultdict[str, list[Any]] = defaultdict(list)
    refunds_by_order: defaultdict[str, list[Any]] = defaultdict(list)
    refund_events_by_order: defaultdict[str, list[Any]] = defaultdict(list)
    verifications_by_order: defaultdict[str, list[VerificationEvidence]] = defaultdict(list)
    canceled_verify_ids: set[str] = set()
    canceled_coupon_ids: set[str] = set()

    for batch in _batch(requested):
        rounds = session.scalars(
            select(ClueAssignmentRound)
            .where(ClueAssignmentRound.order_id.in_(batch))
            .where(ClueAssignmentRound.execution_mode == "formal")
        ).all()
        round_ids: list[str] = []
        for row in rounds:
            evidence = AssignmentRoundEvidence.from_row(row)
            rounds_by_order[evidence.order_id].append(evidence)
            round_ids.append(evidence.assignment_round_id)
        if round_ids:
            follow_rows = session.scalars(
                select(ClueFollowUpRecord)
                .where(ClueFollowUpRecord.assignment_round_id.in_(round_ids))
                .where(ClueFollowUpRecord.created_at <= cutoff)
            ).all()
            for row in follow_rows:
                follows_by_round[str(row.assignment_round_id)].append(FollowUpEvidence.from_row(row))

        # Use column mappings instead of ORM hydration for raw orders.  Ranking
        # periods can contain old assigned rounds whose sale/order row is far
        # outside the window; loading those ORM entities would defeat the
        # bounded sales query and pollute callers' identity-map measurements.
        order_rows = session.execute(
            select(
                RawDouyinOrder.order_id,
                RawDouyinOrder.order_status,
                RawDouyinOrder.order_status_normalized,
                RawDouyinOrder.raw_payload,
                RawDouyinOrder.source_observed_at,
                RawDouyinOrder.updated_at,
            ).where(RawDouyinOrder.order_id.in_(batch))
        ).mappings().all()
        for row in order_rows:
            raw_orders[str(row["order_id"])] = SimpleNamespace(**row)
        if include_raw_clues:
            for row in session.scalars(select(RawDouyinClue).where(RawDouyinClue.order_id.in_(batch))).all():
                observed = _status_observed_at(row)
                if observed is None or observed <= cutoff:
                    raw_clues_by_order[str(row.order_id)].append(row)
        for row in session.scalars(select(RawDouyinOrderCoupon).where(RawDouyinOrderCoupon.order_id.in_(batch))).all():
            observed = _status_observed_at(row)
            if observed is None or observed <= cutoff:
                coupons_by_order[str(row.order_id)].append(row)
        for row in session.scalars(select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.order_id.in_(batch))).all():
            observed = _status_observed_at(row)
            if observed is None or observed <= cutoff:
                refunds_by_order[str(row.order_id)].append(row)

        for row in session.scalars(select(DouyinRefundEvent).where(DouyinRefundEvent.order_id.in_(batch))).all():
            observed = _status_observed_at(row)
            if observed is None or observed <= cutoff:
                refund_events_by_order[str(row.order_id)].append(row)

        raw_verify_rows = session.execute(
            select(RawDouyinOrderCoupon.order_id, RawDouyinVerifyRecord)
            .join(RawDouyinVerifyRecord, RawDouyinVerifyRecord.coupon_id == RawDouyinOrderCoupon.coupon_id)
            .where(RawDouyinOrderCoupon.order_id.in_(batch))
        ).all()
        for order_id, row in raw_verify_rows:
            verify_at = _aware(row.verify_time)
            if verify_at is None or verify_at > cutoff:
                continue
            observed = _aware(row.source_observed_at)
            if observed is not None and observed > cutoff:
                continue
            cancel_at = _aware(row.cancel_time)
            if cancel_at is not None and cancel_at <= cutoff:
                canceled_verify_ids.add(str(row.verify_id))
                if row.coupon_id:
                    canceled_coupon_ids.add(str(row.coupon_id))
                continue
            if _normal_status(row.verify_status) not in VERIFY_SUCCESS_STATUSES:
                continue
            verifications_by_order[str(order_id)].append(
                VerificationEvidence(
                    verify_id=str(row.verify_id),
                    order_id=str(order_id),
                    verified_at=verify_at,
                    poi_id=_text(row.poi_id),
                    cancel_at=cancel_at,
                    observed_at=observed or verify_at,
                    source="raw_verify",
                )
            )

        settlement_rows = session.execute(
            select(SettlementOrderDetail)
            .where(SettlementOrderDetail.order_id.in_(batch))
            .where(SettlementOrderDetail.is_verified.is_(True))
            .where(SettlementOrderDetail.verify_time.is_not(None))
        ).scalars().all()
        for row in settlement_rows:
            verify_at = _aware(row.verify_time)
            if verify_at is None or verify_at > cutoff:
                continue
            if (
                row.verify_id is not None and str(row.verify_id) in canceled_verify_ids
            ) or str(row.coupon_id) in canceled_coupon_ids:
                continue
            observed_at = _aware(row.updated_at) or verify_at
            if observed_at > cutoff:
                continue
            verifications_by_order[str(row.order_id)].append(
                VerificationEvidence(
                    verify_id=str(row.verify_id or row.coupon_id),
                    order_id=str(row.order_id),
                    verified_at=verify_at,
                    store_id=_text(row.verify_store_id),
                    observed_at=observed_at,
                    source="settlement",
                )
            )

    # Round-level verification summaries are a legacy projection and are still
    # useful when a raw coupon bridge has not arrived.  Do not use a canceled
    # raw verification to populate them; cancellation handling above is the
    # source of truth when raw evidence exists.
    for order_id, rows in rounds_by_order.items():
        for row in rows:
            verified_at = row.verified_at
            if verified_at is None:
                continue
            verified_at = _aware(verified_at)
            if verified_at is None or verified_at > cutoff:
                continue
            observed_at = _aware(row.updated_at) or verified_at
            if observed_at > cutoff:
                continue
            verifications_by_order[order_id].append(
                VerificationEvidence(
                    verify_id=f"round:{row.assignment_round_id}",
                    order_id=order_id,
                    verified_at=verified_at,
                    store_id=row.verified_store_id,
                    observed_at=observed_at,
                    source="assignment_round",
                )
            )

    result: dict[str, ClueFollowUpEvidence] = {}
    for order_id in requested:
        terminal = _terminal_from_rows(
            order_id,
            raw_order=raw_orders.get(order_id),
            raw_clues=raw_clues_by_order.get(order_id, ()),
            coupons=coupons_by_order.get(order_id, ()),
            refunds=refunds_by_order.get(order_id, ()),
            refund_events=refund_events_by_order.get(order_id, ()),
            verifications=verifications_by_order.get(order_id, ()),
            observed_through=cutoff,
        )
        result[order_id] = ClueFollowUpEvidence(
            order_id=order_id,
            rounds=tuple(sorted(rounds_by_order.get(order_id, ()), key=lambda item: (item.assigned_at or datetime.min.replace(tzinfo=timezone.utc), item.round_no, item.assignment_round_id))),
            follow_ups_by_round={
                round_id: tuple(sorted(rows, key=lambda item: (item.created_at or datetime.min.replace(tzinfo=timezone.utc), item.follow_up_record_id)))
                for round_id, rows in follows_by_round.items()
                if any(item.assignment_round_id == round_id and item.order_id == order_id for item in rows)
            },
            verifications=tuple(verifications_by_order.get(order_id, ())),
            terminal=terminal,
            observed_through=cutoff,
        )
    return result


def load_terminal_evidence(
    session: Session,
    order_ids: Iterable[str],
    *,
    observed_through: datetime | None = None,
    include_raw_clues: bool = True,
) -> dict[str, TerminalEvidence]:
    """Load only terminal evidence for lifecycle/API/repair callers.

    This intentionally avoids the follow-record and full-round history queries
    performed by :func:`load_clue_followup_evidence`.  Order IDs are still
    batched so a stale-clue repair cannot turn a bounded job into a giant
    ``IN`` expression or one query per order.
    """

    requested = {str(value) for value in order_ids if _text(value)}
    cutoff = _aware(observed_through) or _now_utc()
    if not requested:
        return {}
    raw_orders: dict[str, Any] = {}
    raw_clues_by_order: defaultdict[str, list[Any]] = defaultdict(list)
    coupons_by_order: defaultdict[str, list[Any]] = defaultdict(list)
    refunds_by_order: defaultdict[str, list[Any]] = defaultdict(list)
    refund_events_by_order: defaultdict[str, list[Any]] = defaultdict(list)
    verifications_by_order: defaultdict[str, list[VerificationEvidence]] = defaultdict(list)
    round_verified_by_order: defaultdict[str, list[AssignmentRoundEvidence]] = defaultdict(list)
    canceled_verify_ids: set[str] = set()
    canceled_coupon_ids: set[str] = set()

    for batch in _batch(requested):
        order_rows = session.execute(
            select(
                RawDouyinOrder.order_id,
                RawDouyinOrder.order_status,
                RawDouyinOrder.order_status_normalized,
                RawDouyinOrder.raw_payload,
                RawDouyinOrder.source_observed_at,
                RawDouyinOrder.updated_at,
            ).where(RawDouyinOrder.order_id.in_(batch))
        ).mappings().all()
        for row in order_rows:
            raw_orders[str(row["order_id"])] = SimpleNamespace(**row)

        if include_raw_clues:
            for row in session.scalars(select(RawDouyinClue).where(RawDouyinClue.order_id.in_(batch))).all():
                observed = _status_observed_at(row)
                if observed is None or observed <= cutoff:
                    raw_clues_by_order[str(row.order_id)].append(row)
        for row in session.scalars(select(RawDouyinOrderCoupon).where(RawDouyinOrderCoupon.order_id.in_(batch))).all():
            observed = _status_observed_at(row)
            if observed is None or observed <= cutoff:
                coupons_by_order[str(row.order_id)].append(row)
        for row in session.scalars(select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.order_id.in_(batch))).all():
            observed = _status_observed_at(row)
            if observed is None or observed <= cutoff:
                refunds_by_order[str(row.order_id)].append(row)

        for row in session.scalars(select(DouyinRefundEvent).where(DouyinRefundEvent.order_id.in_(batch))).all():
            observed = _status_observed_at(row)
            if observed is None or observed <= cutoff:
                refund_events_by_order[str(row.order_id)].append(row)

        raw_verify_rows = session.execute(
            select(RawDouyinOrderCoupon.order_id, RawDouyinVerifyRecord)
            .join(RawDouyinVerifyRecord, RawDouyinVerifyRecord.coupon_id == RawDouyinOrderCoupon.coupon_id)
            .where(RawDouyinOrderCoupon.order_id.in_(batch))
        ).all()
        for order_id, row in raw_verify_rows:
            verify_at = _aware(row.verify_time)
            if verify_at is None or verify_at > cutoff:
                continue
            cancel_at = _aware(row.cancel_time)
            source_observed = _aware(row.source_observed_at)
            if source_observed is not None and source_observed > cutoff:
                continue
            if cancel_at is not None and cancel_at <= cutoff:
                canceled_verify_ids.add(str(row.verify_id))
                if row.coupon_id:
                    canceled_coupon_ids.add(str(row.coupon_id))
                continue
            if _normal_status(row.verify_status) not in VERIFY_SUCCESS_STATUSES:
                continue
            verifications_by_order[str(order_id)].append(
                VerificationEvidence(
                    verify_id=str(row.verify_id),
                    order_id=str(order_id),
                    verified_at=verify_at,
                    poi_id=_text(row.poi_id),
                    cancel_at=cancel_at,
                    observed_at=source_observed or verify_at,
                    source="raw_verify",
                )
            )
        settlement_rows = session.execute(
            select(SettlementOrderDetail)
            .where(SettlementOrderDetail.order_id.in_(batch))
            .where(SettlementOrderDetail.is_verified.is_(True))
            .where(SettlementOrderDetail.verify_time.is_not(None))
        ).scalars().all()
        for row in settlement_rows:
            verify_at = _aware(row.verify_time)
            if verify_at is None or verify_at > cutoff:
                continue
            if (
                row.verify_id is not None and str(row.verify_id) in canceled_verify_ids
            ) or str(row.coupon_id) in canceled_coupon_ids:
                continue
            observed_at = _aware(row.updated_at) or verify_at
            if observed_at > cutoff:
                continue
            verifications_by_order[str(row.order_id)].append(
                VerificationEvidence(
                    verify_id=str(row.verify_id or row.coupon_id),
                    order_id=str(row.order_id),
                    verified_at=verify_at,
                    store_id=_text(row.verify_store_id),
                    observed_at=observed_at,
                    source="settlement",
                )
            )
        round_rows = session.execute(
            select(
                ClueAssignmentRound.assignment_round_id,
                ClueAssignmentRound.order_id,
                ClueAssignmentRound.round_no,
                ClueAssignmentRound.assigned_store_id,
                ClueAssignmentRound.assigned_at,
                ClueAssignmentRound.execution_mode,
                ClueAssignmentRound.verified_store_id,
                ClueAssignmentRound.verified_at,
                ClueAssignmentRound.updated_at,
            )
            .where(ClueAssignmentRound.order_id.in_(batch))
            .where(ClueAssignmentRound.execution_mode == "formal")
        ).mappings().all()
        for row in round_rows:
            round_value = AssignmentRoundEvidence(
                assignment_round_id=str(row["assignment_round_id"]),
                order_id=str(row["order_id"]),
                round_no=int(row["round_no"] or 0),
                assigned_store_id=_text(row["assigned_store_id"]),
                assigned_at=_aware(row["assigned_at"]),
                execution_mode=_text(row["execution_mode"]) or "formal",
                verified_store_id=_text(row["verified_store_id"]),
                verified_at=_aware(row["verified_at"]),
                updated_at=_aware(row["updated_at"]),
            )
            round_verified_by_order[round_value.order_id].append(round_value)

    for order_id, rows in round_verified_by_order.items():
        for row in rows:
            if row.verified_at is not None and row.verified_at <= cutoff:
                observed_at = _aware(row.updated_at) or row.verified_at
                if observed_at > cutoff:
                    continue
                verifications_by_order[order_id].append(
                    VerificationEvidence(
                        verify_id=f"round:{row.assignment_round_id}",
                        order_id=order_id,
                        verified_at=row.verified_at,
                        store_id=row.verified_store_id,
                        observed_at=observed_at,
                        source="assignment_round",
                    )
                )

    return {
        order_id: _terminal_from_rows(
            order_id,
            raw_order=raw_orders.get(order_id),
            raw_clues=raw_clues_by_order.get(order_id, ()),
            coupons=coupons_by_order.get(order_id, ()),
            refunds=refunds_by_order.get(order_id, ()),
            refund_events=refund_events_by_order.get(order_id, ()),
            verifications=verifications_by_order.get(order_id, ()),
            observed_through=cutoff,
        )
        for order_id in requested
    }


def bulk_evaluate_clue_followup_metrics(
    session: Session,
    order_ids: Iterable[str],
    *,
    round_rows: Iterable[AssignmentRoundEvidence | Any] | None = None,
    observed_through: datetime | None = None,
) -> dict[str, FollowUpMetric]:
    """Evaluate selected rounds after one shared, batched evidence load."""

    selected = [
        row if isinstance(row, AssignmentRoundEvidence) else AssignmentRoundEvidence.from_row(row)
        for row in (round_rows or ())
    ]
    loaded = load_clue_followup_evidence(session, order_ids, observed_through=observed_through)
    if not selected:
        selected = [row for evidence in loaded.values() for row in evidence.rounds]
    metrics: dict[str, FollowUpMetric] = {}
    for row in selected:
        evidence = loaded.get(row.order_id)
        metrics[row.assignment_round_id] = evaluate_clue_followup_round(
            row,
            follow_ups=evidence.follow_ups_for(row.assignment_round_id) if evidence else (),
            terminal=evidence.terminal if evidence else TerminalEvidence(None, None, None),
            observed_through=observed_through,
        )
    return metrics


__all__ = [
    "AssignmentRoundEvidence",
    "CLUE_FOLLOWUP_METRIC_DEFINITIONS",
    "ClueFollowUpEvidence",
    "FollowUpEvidence",
    "FollowUpMetric",
    "FOLLOW_UP_METRIC_VERSION",
    "TerminalEvidence",
    "VerificationEvidence",
    "bulk_evaluate_clue_followup_metrics",
    "evaluate_clue_followup_round",
    "load_clue_followup_evidence",
    "load_terminal_evidence",
]
