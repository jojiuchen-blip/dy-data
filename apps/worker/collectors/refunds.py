from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DataQualityIssue,
    DouyinRefundEvent,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinRefundRecord,
)
from apps.worker.collectors.normalizers import data_items, first, get_path, source_datetime, text
from apps.worker.collectors.types import CollectionWindow, PhaseStats
from apps.worker.repositories import payload_fingerprint, upsert_data_quality_issue, upsert_refund_event


REFUND_STATUS_MAP = {
    "9": 1,
    "10": 1,
    "20": 1,
    "30": 1,
    "50": 2,
    "25": 3,
    "59": 3,
    "40": 4,
}


class RefundCollectionError(RuntimeError):
    pass


def collect_refunds(
    session: Session,
    client: Any,
    window: CollectionWindow,
    *,
    source_run_id: str,
    page_size: int = 100,
) -> PhaseStats:
    """Collect one Shanghai business-day refund window.

    Invalid rows are retained as DQI evidence and counted as skipped; only a
    row with a stable platform ID and complete business facts creates a
    ``DouyinRefundEvent``.
    """

    stats = PhaseStats(name="refunds")
    try:
        rows = _iter_refund_rows(client, window, page_size=max(1, int(page_size)))
        for payload in rows:
            stats.fetched += 1
            if _process_refund(session, payload, source_run_id=source_run_id):
                stats.upserted += 1
            else:
                stats.skipped += 1
    except Exception as exc:  # noqa: BLE001 - source boundary must fail closed.
        stats.failed += 1
        issue_type = (
            "refund_cursor_nonadvance"
            if "cursor" in str(exc).lower()
            else "refund_collection_failed"
        )
        _record_issue(
            session,
            issue_type,
            stable_id=None,
            order_id=None,
            source_run_id=source_run_id,
            message=f"Refund collection stopped safely: {exc}",
            payload={"window": window.as_metadata()},
        )
        session.flush()
        if isinstance(exc, RefundCollectionError):
            raise
        raise RefundCollectionError(str(exc)) from exc
    return stats


def _iter_refund_rows(
    client: Any,
    window: CollectionWindow,
    *,
    page_size: int,
) -> Iterator[dict[str, Any]]:
    iterator = getattr(client, "iter_refunds", None)
    if callable(iterator):
        yield from iterator(window.start, window.end, page_size=page_size)
        return

    query = getattr(client, "query_refunds", None)
    if not callable(query):
        raise RefundCollectionError("refund client has no query_refunds/iter_refunds")
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        payload = query(window.start, window.end, cursor=cursor, page_size=page_size)
        for row in _extract_refunds(payload):
            yield row
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            raise RefundCollectionError("refund page missing explicit has_more")
        page_info = data.get("page_info") if isinstance(data.get("page_info"), dict) else {}
        raw_has_more = (
            data.get("has_more")
            if data.get("has_more") is not None
            else page_info.get("has_more")
        )
        has_more = _explicit_bool(raw_has_more)
        next_cursor = text(first(data, "next_cursor", "cursor")) or text(first(page_info, "next_cursor", "cursor"))
        if not next_cursor:
            rows = _extract_refunds(payload)
            if rows:
                next_cursor = text(first(rows[-1], "cursor", "next_cursor"))
        if has_more is False:
            return
        if has_more is None:
            raise RefundCollectionError("refund has_more must be explicit true or false")
        if not next_cursor:
            raise RefundCollectionError("refund cursor missing while has_more is true")
        if next_cursor == cursor or next_cursor in seen_cursors:
            raise RefundCollectionError(f"refund cursor did not advance: {next_cursor!r}")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _extract_refunds(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return data_items(
        payload,
        "refunds",
        "after_sales",
        "after_sale_orders",
        "after_sale_order_list",
        "records",
        "list",
    )


def _explicit_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "off"}:
            return False
        if normalized in {"true", "1", "yes", "on"}:
            return True
    return None


def _process_refund(session: Session, payload: dict[str, Any], *, source_run_id: str) -> bool:
    stable_id = _stable_refund_id(payload)
    order_id = text(first(payload, "order_id", "order.order_id", "trade_order_id"))
    raw_status = text(first(payload, "refund_status", "status", "after_sale_status", "state"))
    normalized_status = REFUND_STATUS_MAP.get((raw_status or "").strip().lower(), 0)
    source_observed_at = _observation_time(payload)
    amount, amount_conflict, amount_invalid, amount_ambiguous = _refund_amount(payload)
    if amount_invalid or amount_conflict or amount_ambiguous:
        # Preserve the raw payload, but never persist a guessed/truncated
        # amount that could accidentally reach the business event.
        amount = None
    fingerprint = payload_fingerprint(payload)

    if not stable_id:
        _record_issue(
            session,
            "refund_missing_stable_id",
            stable_id=None,
            order_id=order_id,
            source_run_id=source_run_id,
            message="Refund payload has no explicit after_sale_id/refund_event_id",
            payload=payload,
        )
        return False
    if not order_id:
        _record_issue(session, "refund_missing_order", stable_id, None, source_run_id, "Refund payload has no order_id", payload)
        return False

    raw = session.scalar(
        select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.source_record_key == stable_id)
    )
    existing_event = session.scalar(
        select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == stable_id)
    )
    identity_conflict = bool(
        (raw is not None and raw.order_id != order_id)
        or (existing_event is not None and existing_event.order_id != order_id)
    )
    if raw is None and existing_event is not None and existing_event.order_id != order_id:
        _record_issue(
            session,
            "refund_stable_id_order_conflict",
            stable_id,
            order_id,
            source_run_id,
            "Stable refund ID is already bound to a different order",
            payload,
            severity="error",
        )
        session.flush()
        return False
    if raw is None:
        raw = RawDouyinRefundRecord(
            source_record_key=stable_id,
            refund_id=stable_id,
            order_id=order_id,
            raw_refund_status=raw_status,
            normalized_refund_status=normalized_status,
            refund_amount_cent=amount,
            refund_applied_at=_source_time(payload, "refund_applied_at", "apply_time", "created_at"),
            refund_completed_at=_source_time(payload, "refund_completed_at", "completed_at", "finish_time", "refund_done_at"),
            source_observed_at=source_observed_at,
            source_run_id=source_run_id,
            payload_hash=fingerprint,
            raw_payload=payload,
        )
        session.add(raw)
    else:
        apply_business = not identity_conflict and _is_newer_observation(
            raw.source_observed_at,
            raw.payload_hash,
            source_observed_at,
            fingerprint,
        )
        if apply_business:
            raw.order_id = order_id
            raw.refund_id = stable_id
            raw.raw_refund_status = raw_status
            raw.normalized_refund_status = normalized_status
            raw.refund_amount_cent = amount
            raw.refund_applied_at = _source_time(payload, "refund_applied_at", "apply_time", "created_at")
            raw.refund_completed_at = _source_time(payload, "refund_completed_at", "completed_at", "finish_time", "refund_done_at")
            raw.source_observed_at = source_observed_at
            raw.payload_hash = fingerprint
            raw.raw_payload = payload
            raw.source_run_id = source_run_id
    session.flush()

    if identity_conflict:
        _record_issue(
            session,
            "refund_stable_id_order_conflict",
            stable_id,
            order_id,
            source_run_id,
            "Stable refund ID is already bound to a different order",
            payload,
            severity="error",
        )
        session.flush()
        return False

    # Project only the accepted current observation.  A stale replay must not
    # be allowed to update the business event from its incoming payload.
    current_payload = dict(raw.raw_payload or {})
    current_status = raw.normalized_refund_status
    current_amount = raw.refund_amount_cent
    current_observed_at = raw.source_observed_at
    current_order_id = raw.order_id
    current_type = _refund_type(current_payload)
    occurred_at = _business_occurred_at(current_payload, current_status)
    (
        _amount_value,
        current_amount_conflict,
        current_amount_invalid,
        current_amount_ambiguous,
    ) = _refund_amount(current_payload)

    blocked = False
    if not raw.raw_refund_status:
        _record_issue(session, "refund_missing_status", stable_id, current_order_id, source_run_id, "Refund payload has no status", current_payload)
        blocked = True
    elif current_status == 0:
        _record_issue(session, "refund_unknown_status", stable_id, current_order_id, source_run_id, f"Unknown refund status: {raw.raw_refund_status}", current_payload, severity="error")
        blocked = True
    if occurred_at is None:
        _record_issue(session, "refund_missing_time", stable_id, current_order_id, source_run_id, "Refund payload has no explicit business occurrence time", current_payload)
        blocked = True
    if current_amount_ambiguous:
        _record_issue(
            session,
            "refund_amount_unit_ambiguous",
            stable_id,
            current_order_id,
            source_run_id,
            "Refund amount field does not explicitly declare cents",
            current_payload,
            severity="error",
        )
        blocked = True
    elif current_amount_invalid:
        _record_issue(
            session,
            "refund_invalid_amount",
            stable_id,
            current_order_id,
            source_run_id,
            "Refund amount must be a non-negative integer number of cents",
            current_payload,
            severity="error",
        )
        blocked = True
    elif current_amount_conflict:
        _record_issue(session, "refund_amount_conflict", stable_id, current_order_id, source_run_id, "Refund payload amount candidates conflict", current_payload, severity="error")
        blocked = True
    elif current_amount is None:
        _record_issue(session, "refund_missing_amount", stable_id, current_order_id, source_run_id, "Refund payload has no unambiguous amount", current_payload)
        blocked = True
    if current_type is None:
        issue_type = "refund_missing_type" if not first(current_payload, "refund_type", "type") else "refund_unknown_type"
        _record_issue(session, issue_type, stable_id, current_order_id, source_run_id, "Refund type is missing or unsupported", current_payload, severity="error")
        blocked = True

    if session.scalar(
        select(RawDouyinOrder.id).where(RawDouyinOrder.order_id == current_order_id)
    ) is None:
        _record_issue(
            session,
            "refund_unknown_order",
            stable_id,
            current_order_id,
            source_run_id,
            "Refund order_id does not exist in raw order evidence",
            current_payload,
            severity="error",
        )
        blocked = True

    coupon_id, coupon_ambiguous = _resolve_coupon(session, current_payload, current_order_id)
    if coupon_ambiguous:
        _record_issue(session, "refund_coupon_ambiguous", stable_id, current_order_id, source_run_id, "Multiple coupons exist and refund has no explicit coupon evidence", current_payload, severity="error")
    explicit_coupon_id = _explicit_coupon_id(current_payload)
    if explicit_coupon_id:
        explicit_coupon = session.scalar(
            select(RawDouyinOrderCoupon).where(
                RawDouyinOrderCoupon.coupon_id == explicit_coupon_id
            )
        )
        if explicit_coupon is None:
            _record_issue(
                session,
                "refund_coupon_missing",
                stable_id,
                current_order_id,
                source_run_id,
                "Refund payload references a coupon that does not exist",
                current_payload,
                severity="error",
            )
            blocked = True
        elif explicit_coupon.order_id != current_order_id:
            _record_issue(
                session,
                "refund_coupon_order_mismatch",
                stable_id,
                current_order_id,
                source_run_id,
                "Refund coupon belongs to a different order",
                current_payload,
                severity="error",
            )
            blocked = True

    if blocked:
        session.flush()
        return False

    _upsert_refund_event(
        session,
        refund_event_id=stable_id,
        order_id=current_order_id,
        coupon_id=coupon_id,
        refund_type=int(current_type),
        refund_status=current_status,
        refund_amount_cent=int(current_amount),
        occurred_at=occurred_at,
        source_run_id=source_run_id,
        source_observed_at=current_observed_at,
        payload_fingerprint=raw.payload_hash,
        observation_key=f"{stable_id}:{raw.payload_hash}",
        raw_payload=current_payload,
    )
    return True


def _upsert_refund_event(
    session: Session,
    *,
    refund_event_id: str,
    order_id: str,
    coupon_id: str | None,
    refund_type: int,
    refund_status: int,
    refund_amount_cent: int,
    occurred_at: datetime,
    source_run_id: str,
    source_observed_at: datetime | None,
    payload_fingerprint: str,
    observation_key: str,
    raw_payload: dict[str, Any],
) -> DouyinRefundEvent:
    return upsert_refund_event(
        session,
        refund_event_id,
        order_id=order_id,
        coupon_id=coupon_id,
        refund_type=refund_type,
        refund_status=refund_status,
        refund_amount_cent=refund_amount_cent,
        occurred_at=occurred_at,
        source_run_id=source_run_id,
        source_observed_at=source_observed_at,
        payload_fingerprint=payload_fingerprint,
        observation_key=observation_key,
        raw_payload=raw_payload,
    )


def _stable_refund_id(payload: dict[str, Any]) -> str | None:
    return text(first(payload, "after_sale_id", "refund_event_id", "after_sale.after_sale_id", "refund_event.refund_event_id"))


def _refund_type(payload: dict[str, Any]) -> int | None:
    value = str(first(payload, "refund_type", "type") or "").strip().lower()
    if value in {"1", "partial", "partial_refund"}:
        return 1
    if value in {"2", "full", "full_refund", "all"}:
        return 2
    return None


def _source_time(payload: dict[str, Any], *keys: str) -> datetime | None:
    return source_datetime(first(payload, *keys))


def _refund_amount(payload: dict[str, Any]) -> tuple[int | None, bool, bool, bool]:
    """Parse only fields that explicitly declare cents.

    Ambiguous amount names and unknown ``*_cent`` components are retained in
    raw evidence but never interpreted as the refund total.  The only
    contract-frozen amount key is the exact ``refund_amount_cent`` name,
    including when it appears in a nested object.
    """

    candidates: list[int] = []
    invalid = False
    ambiguous = False
    untrusted_cent = False
    ambiguous_keys = {
        "refund_amount",
        "refund_fee",
        "refund_money",
        "amount",
        "apply_amount",
        "total_refund_amount",
        "user_refund_amount",
        "real_refund_amount",
        "market_refund_amount",
    }

    def visit(value: Any) -> None:
        nonlocal ambiguous, invalid, untrusted_cent
        if not isinstance(value, dict):
            return
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip().lower()
            if key in ambiguous_keys and not isinstance(raw_value, dict) and raw_value not in (None, ""):
                ambiguous = True
            if isinstance(raw_value, dict):
                visit(raw_value)
                continue
            # Only this contract-frozen refund field is authoritative.  Other
            # *_cent values (platform/shipping fees, etc.) are distinct
            # components and must never be mistaken for the refund total.  If
            # one is supplied alongside a valid refund total, fail closed
            # instead of silently ignoring a potentially competing amount.
            if key.endswith("_cent") and key != "refund_amount_cent" and raw_value not in (None, ""):
                untrusted_cent = True
            if key != "refund_amount_cent" or raw_value in (None, ""):
                continue
            candidate = raw_value
            try:
                decimal_value = Decimal(str(candidate))
                if decimal_value < 0 or decimal_value != decimal_value.to_integral_value():
                    invalid = True
                    continue
                candidates.append(int(decimal_value))
            except (InvalidOperation, OverflowError, TypeError, ValueError):
                invalid = True

    visit(payload)
    if not candidates:
        return None, False, invalid, ambiguous
    unique = set(candidates)
    conflict = len(unique) > 1 or untrusted_cent
    return (None if invalid or ambiguous or conflict else candidates[0]), conflict, invalid, ambiguous


def _explicit_coupon_id(payload: dict[str, Any]) -> str | None:
    return text(first(payload, "coupon_id", "certificate_id", "coupon_code", "certificate.code"))


def _resolve_coupon(session: Session, payload: dict[str, Any], order_id: str) -> tuple[str | None, bool]:
    explicit = text(first(payload, "coupon_id", "certificate_id", "coupon_code", "certificate.code"))
    if explicit:
        return explicit, False
    rows = list(
        session.scalars(
            select(RawDouyinOrderCoupon.coupon_id)
            .where(RawDouyinOrderCoupon.order_id == order_id)
            .order_by(RawDouyinOrderCoupon.coupon_id)
            .limit(2)
        )
    )
    if len(rows) == 1:
        return str(rows[0]), False
    return None, len(rows) > 1


def _is_newer_observation(
    current_at: datetime | None,
    current_key: str | None,
    candidate_at: datetime | None,
    candidate_key: str,
) -> bool:
    if current_at is None:
        return candidate_at is not None
    if candidate_at is None:
        return False
    current = current_at if current_at.tzinfo else current_at.replace(tzinfo=timezone.utc)
    candidate = candidate_at if candidate_at.tzinfo else candidate_at.replace(tzinfo=timezone.utc)
    if candidate != current:
        return candidate > current
    return candidate_key > str(current_key or "")


def _observation_time(payload: dict[str, Any]) -> datetime | None:
    return source_datetime(
        first(payload, "modify_time", "update_time", "updated_at", "completed_at", "refund_done_at", "apply_time", "refund_applied_at")
    )


def _business_occurred_at(payload: dict[str, Any], normalized_status: int) -> datetime | None:
    if normalized_status == 1:
        return source_datetime(first(payload, "refund_applied_at", "apply_time", "refund_created_at", "created_at"))
    if normalized_status == 2:
        return source_datetime(first(payload, "refund_completed_at", "completed_at", "refund_done_at", "finish_time"))
    if normalized_status == 3:
        return source_datetime(first(payload, "failed_at", "refund_failed_at", "refund_completed_at", "completed_at"))
    if normalized_status == 4:
        return source_datetime(first(payload, "cancelled_at", "canceled_at", "cancel_time", "refund_cancelled_at"))
    return None


def _record_issue(
    session: Session,
    issue_type: str,
    stable_id: str | None,
    order_id: str | None,
    source_run_id: str,
    message: str,
    payload: dict[str, Any],
    *,
    severity: str = "error",
) -> DataQualityIssue:
    digest = hashlib.sha256(
        f"{issue_type}|{stable_id or ''}|{order_id or ''}".encode("utf-8")
    ).hexdigest()[:32]
    return upsert_data_quality_issue(
        session,
        f"refund-{issue_type}-{digest}",
        issue_type=issue_type,
        order_id=order_id,
        severity=severity,
        message=message,
        raw_context_json=payload,
        source_run_id=source_run_id,
    )
