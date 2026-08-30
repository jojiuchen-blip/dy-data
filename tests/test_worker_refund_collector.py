from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
import pytest

from apps.api.dy_api.models import (
    DataQualityIssue,
    DouyinRefundEvent,
    JobImpact,
    RawDouyinRefundRecord,
)
from apps.worker.collectors.refunds import RefundCollectionError, collect_refunds
from apps.worker.collectors.types import CollectionWindow
from apps.worker.repositories import upsert_order_coupon, upsert_raw_order, upsert_refund_event


def window() -> CollectionWindow:
    return CollectionWindow(
        start=datetime.fromisoformat("2026-08-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-08-02T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )


class FakeRefundClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def iter_refunds(self, start: datetime, end: datetime, *, page_size: int = 100):
        yield from self.rows


def test_refund_requires_stable_id_and_upserts_explicit_event_once(db_session: Session) -> None:
    upsert_raw_order(db_session, "order-1", order_status_normalized="paid")
    rows = [
        {
            "after_sale_id": "as-1",
            "order_id": "order-1",
            "status": 50,
            "refund_type": 1,
            "refund_amount_cent": 1234,
            "completed_at": "2026-08-01T10:00:00+08:00",
        },
        {
            "order_id": "order-2",
            "status": 50,
            "refund_amount": 99,
            "completed_at": "2026-08-01T10:00:00+08:00",
        },
    ]
    stats = collect_refunds(db_session, FakeRefundClient(rows), window(), source_run_id="run-1")
    assert stats.fetched == 2
    assert stats.upserted == 1
    assert stats.skipped == 1
    raw = db_session.scalar(select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.source_record_key == "as-1"))
    assert raw is not None
    assert raw.raw_refund_status == "50"
    assert raw.normalized_refund_status == 2
    event = db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == "as-1"))
    assert event is not None
    assert event.refund_amount_cent == 1234
    assert event.order_id == "order-1"
    assert db_session.scalar(select(DataQualityIssue).where(DataQualityIssue.issue_type == "refund_missing_stable_id")) is not None


def test_refund_unknown_status_is_blocked_without_business_event(db_session: Session) -> None:
    rows = [
        {
            "refund_event_id": "refund-unknown",
            "order_id": "order-1",
            "status": 777,
            "refund_type": 1,
            "refund_amount": 1234,
            "completed_at": "2026-08-01T10:00:00+08:00",
        }
    ]
    stats = collect_refunds(db_session, FakeRefundClient(rows), window(), source_run_id="run-unknown")
    assert stats.upserted == 0
    assert stats.skipped == 1
    assert db_session.scalar(select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.source_record_key == "refund-unknown")) is not None
    assert db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == "refund-unknown")) is None
    issue = db_session.scalar(select(DataQualityIssue).where(DataQualityIssue.issue_type == "refund_unknown_status"))
    assert issue is not None
    assert issue.severity == "error"


def test_refund_status_25_and_59_normalize_to_failed_and_overlap_is_idempotent(db_session: Session) -> None:
    upsert_raw_order(db_session, "order-25", order_status_normalized="paid")
    upsert_raw_order(db_session, "order-59", order_status_normalized="paid")
    rows = [
        {
            "refund_event_id": "refund-25",
            "order_id": "order-25",
            "status": 25,
            "refund_type": 1,
            "refund_amount_cent": 100,
            "apply_time": "2026-08-01T10:00:00+08:00",
            "failed_at": "2026-08-01T10:05:00+08:00",
        },
        {
            "refund_event_id": "refund-59",
            "order_id": "order-59",
            "status": 59,
            "refund_type": 1,
            "refund_amount_cent": 200,
            "apply_time": "2026-08-01T11:00:00+08:00",
            "failed_at": "2026-08-01T11:05:00+08:00",
        },
    ]
    client = FakeRefundClient(rows)
    collect_refunds(db_session, client, window(), source_run_id="run-a")
    collect_refunds(db_session, client, window(), source_run_id="run-b")
    assert db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == "refund-25")).refund_status == 3
    assert db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == "refund-59")).refund_status == 3
    assert db_session.query(RawDouyinRefundRecord).count() == 2
    assert db_session.query(DouyinRefundEvent).count() == 2


def test_refund_missing_required_fields_and_conflicting_amount_are_blocked(db_session: Session) -> None:
    for order_id in ("order-2", "order-3", "order-4", "order-5"):
        upsert_raw_order(db_session, order_id, order_status_normalized="paid")
    rows = [
        {"refund_event_id": "missing-order", "status": 50, "refund_amount_cent": 1, "apply_time": "2026-08-01T10:00:00+08:00"},
        {"refund_event_id": "missing-status", "order_id": "order-2", "refund_amount_cent": 1, "apply_time": "2026-08-01T10:00:00+08:00"},
        {"refund_event_id": "missing-time", "order_id": "order-3", "status": 50, "refund_amount_cent": 1},
        {"refund_event_id": "missing-amount", "order_id": "order-4", "status": 50, "apply_time": "2026-08-01T10:00:00+08:00"},
        {"refund_event_id": "conflict-amount", "order_id": "order-5", "status": 50, "refund_amount_cent": 100, "refund_fee_cent": 200, "apply_time": "2026-08-01T10:00:00+08:00"},
    ]
    stats = collect_refunds(db_session, FakeRefundClient(rows), window(), source_run_id="run-invalid")
    assert stats.upserted == 0
    assert stats.skipped == len(rows)
    assert db_session.query(DouyinRefundEvent).count() == 0
    issue_types = {issue.issue_type for issue in db_session.scalars(select(DataQualityIssue))}
    assert {"refund_missing_order", "refund_missing_status", "refund_missing_time", "refund_missing_amount", "refund_amount_conflict"}.issubset(issue_types)


def test_refund_fractional_or_negative_amount_is_invalid_not_truncated(
    db_session: Session,
) -> None:
    upsert_raw_order(db_session, "order-fractional", order_status_normalized="paid")
    upsert_raw_order(db_session, "order-negative", order_status_normalized="paid")
    rows = [
        {
            "refund_event_id": "fractional-amount",
            "order_id": "order-fractional",
            "status": 50,
            "refund_type": 1,
            "refund_amount_cent": "12.34",
            "completed_at": "2026-08-01T10:00:00+08:00",
        },
        {
            "refund_event_id": "negative-amount",
            "order_id": "order-negative",
            "status": 50,
            "refund_type": 1,
            "refund_amount_cent": -1,
            "completed_at": "2026-08-01T10:00:00+08:00",
        },
    ]
    stats = collect_refunds(
        db_session,
        FakeRefundClient(rows),
        window(),
        source_run_id="run-invalid-amount",
    )
    assert stats.upserted == 0
    assert stats.skipped == 2
    assert db_session.query(DouyinRefundEvent).count() == 0
    invalid_issues = list(
        db_session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.issue_type == "refund_invalid_amount"
            )
        )
    )
    assert len(invalid_issues) == 2
    for stable_id in ("fractional-amount", "negative-amount"):
        raw = db_session.scalar(
            select(RawDouyinRefundRecord).where(
                RawDouyinRefundRecord.source_record_key == stable_id
            )
        )
        assert raw is not None
        assert raw.refund_amount_cent is None
        assert raw.raw_payload


def test_refund_coupon_assignment_requires_explicit_or_unique_single_coupon(db_session: Session) -> None:
    upsert_raw_order(db_session, "order-single", raw_payload={})
    upsert_order_coupon(db_session, "coupon-single", "order-single", raw_payload={})
    upsert_raw_order(db_session, "order-multi", raw_payload={})
    upsert_order_coupon(db_session, "coupon-a", "order-multi", raw_payload={})
    upsert_order_coupon(db_session, "coupon-b", "order-multi", raw_payload={})
    rows = [
        {"refund_event_id": "refund-single", "order_id": "order-single", "status": 50, "refund_type": 1, "refund_amount_cent": 10, "completed_at": "2026-08-01T10:00:00+08:00"},
        {"refund_event_id": "refund-multi", "order_id": "order-multi", "status": 50, "refund_type": 1, "refund_amount_cent": 20, "completed_at": "2026-08-01T10:00:00+08:00"},
    ]
    collect_refunds(db_session, FakeRefundClient(rows), window(), source_run_id="run-coupon")
    single = db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == "refund-single"))
    multi = db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == "refund-multi"))
    assert single is not None and single.coupon_id == "coupon-single"
    assert multi is not None and multi.coupon_id is None
    issue = db_session.scalar(select(DataQualityIssue).where(DataQualityIssue.issue_type == "refund_coupon_ambiguous"))
    assert issue is not None and issue.severity == "error"


def test_refund_successful_observed_at_freezes_first_source_observation(db_session: Session) -> None:
    upsert_raw_order(db_session, "order-s", order_status_normalized="paid")
    first = FakeRefundClient([{"refund_event_id": "refund-success", "order_id": "order-s", "status": 50, "refund_type": 1, "refund_amount_cent": 10, "completed_at": "2026-08-01T10:00:00+08:00"}])
    collect_refunds(db_session, first, window(), source_run_id="run-first")
    event = db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == "refund-success"))
    assert event is not None
    first_observed = event.successful_observed_at
    assert first_observed is not None
    assert first_observed != datetime.fromisoformat("2026-08-01T10:00:00+08:00")
    second = FakeRefundClient([{"refund_event_id": "refund-success", "order_id": "order-s", "status": 50, "refund_type": 1, "refund_amount_cent": 10, "completed_at": "2026-08-02T10:00:00+08:00"}])
    collect_refunds(db_session, second, window(), source_run_id="run-second")
    assert event.successful_observed_at == first_observed


def test_refund_newer_failure_and_old_success_replay_do_not_rewrite_success_timestamp(
    db_session: Session,
) -> None:
    upsert_raw_order(db_session, "order-status-replay", order_status_normalized="paid")
    first = FakeRefundClient([
        {
            "refund_event_id": "refund-status-replay",
            "order_id": "order-status-replay",
            "status": 50,
            "refund_type": 1,
            "refund_amount_cent": 10,
            "modify_time": "2026-08-01T10:00:00+08:00",
            "completed_at": "2026-08-01T10:00:00+08:00",
        }
    ])
    collect_refunds(db_session, first, window(), source_run_id="run-success")
    event = db_session.scalar(
        select(DouyinRefundEvent).where(
            DouyinRefundEvent.refund_event_id == "refund-status-replay"
        )
    )
    assert event is not None
    first_observed = event.successful_observed_at

    newer_failure = FakeRefundClient([
        {
            "refund_event_id": "refund-status-replay",
            "order_id": "order-status-replay",
            "status": 25,
            "refund_type": 1,
            "refund_amount_cent": 10,
            "modify_time": "2026-08-02T10:00:00+08:00",
            "failed_at": "2026-08-02T10:00:00+08:00",
        }
    ])
    collect_refunds(db_session, newer_failure, window(), source_run_id="run-failure")
    assert event.refund_status == 3
    assert event.successful_observed_at == first_observed

    old_success = FakeRefundClient([
        {
            "refund_event_id": "refund-status-replay",
            "order_id": "order-status-replay",
            "status": 50,
            "refund_type": 1,
            "refund_amount_cent": 10,
            "modify_time": "2026-08-01T10:00:00+08:00",
            "completed_at": "2026-08-01T10:00:00+08:00",
        }
    ])
    collect_refunds(db_session, old_success, window(), source_run_id="run-stale-success")
    assert event.refund_status == 3
    assert event.successful_observed_at == first_observed


def test_legacy_refund_without_source_observation_fails_closed_against_old_replay(
    db_session: Session,
) -> None:
    legacy = upsert_refund_event(
        db_session,
        "legacy-refund",
        order_id="legacy-order",
        coupon_id=None,
        refund_type=1,
        refund_status=2,
        refund_amount_cent=10,
        occurred_at=datetime.fromisoformat("2026-08-01T10:00:00+08:00"),
        source_observed_at=None,
        observation_key=None,
        source_run_id="legacy",
        raw_payload={},
    )
    assert legacy.successful_observed_at is not None
    upsert_refund_event(
        db_session,
        "legacy-refund",
        order_id="legacy-order",
        coupon_id=None,
        refund_type=1,
        refund_status=3,
        refund_amount_cent=99,
        occurred_at=datetime.fromisoformat("2026-07-31T10:00:00+08:00"),
        source_observed_at=datetime.fromisoformat("2026-07-31T11:00:00+08:00"),
        observation_key="old-replay",
        source_run_id="old",
        raw_payload={},
    )
    assert legacy.refund_status == 2
    assert legacy.refund_amount_cent == 10


def test_legacy_event_order_conflict_does_not_bind_raw_and_allows_correct_retry(
    db_session: Session,
) -> None:
    upsert_raw_order(db_session, "legacy-order-a", order_status_normalized="paid")
    legacy = upsert_refund_event(
        db_session,
        "legacy-event-only",
        order_id="legacy-order-a",
        coupon_id=None,
        refund_type=1,
        refund_status=2,
        refund_amount_cent=10,
        occurred_at=datetime.fromisoformat("2026-08-01T10:00:00+08:00"),
        source_observed_at=None,
        observation_key=None,
        source_run_id="legacy",
        raw_payload={"legacy": True},
    )

    bad_payload = {
        "refund_event_id": "legacy-event-only",
        "order_id": "legacy-order-b",
        "status": 50,
        "refund_type": 1,
        "refund_amount_cent": 99,
        "completed_at": "2026-08-01T11:00:00+08:00",
    }
    assert collect_refunds(
        db_session,
        FakeRefundClient([bad_payload]),
        window(),
        source_run_id="bad-run",
    ).upserted == 0
    assert db_session.scalar(
        select(RawDouyinRefundRecord).where(
            RawDouyinRefundRecord.source_record_key == "legacy-event-only"
        )
    ) is None
    assert legacy.order_id == "legacy-order-a"
    conflict_issue = db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type == "refund_stable_id_order_conflict"
        )
    )
    assert conflict_issue is not None
    assert conflict_issue.raw_context_json == bad_payload

    good_payload = {
        "refund_event_id": "legacy-event-only",
        "order_id": "legacy-order-a",
        "status": 50,
        "refund_type": 1,
        "refund_amount_cent": 10,
        "completed_at": "2026-08-01T12:00:00+08:00",
    }
    assert collect_refunds(
        db_session,
        FakeRefundClient([good_payload]),
        window(),
        source_run_id="good-run",
    ).upserted == 1
    raw = db_session.scalar(
        select(RawDouyinRefundRecord).where(
            RawDouyinRefundRecord.source_record_key == "legacy-event-only"
        )
    )
    assert raw is not None
    assert raw.order_id == "legacy-order-a"
    assert legacy.order_id == "legacy-order-a"

    assert collect_refunds(
        db_session,
        FakeRefundClient([good_payload]),
        window(),
        source_run_id="good-replay",
    ).upserted == 1
    assert db_session.query(RawDouyinRefundRecord).count() == 1
    assert db_session.query(DouyinRefundEvent).count() == 1
    assert legacy.order_id == "legacy-order-a"


def test_refund_query_cursor_nonadvance_fails_closed_and_is_audited(db_session: Session) -> None:
    class CursorClient:
        def query_refunds(self, start: datetime, end: datetime, *, cursor=None, page_size: int = 100):
            return {"data": {"refunds": [], "has_more": True, "next_cursor": "same"}}

    with pytest.raises(RefundCollectionError):
        collect_refunds(db_session, CursorClient(), window(), source_run_id="run-cursor")


def test_missing_or_unknown_refund_type_blocks_business_event(db_session: Session) -> None:
    upsert_raw_order(db_session, "order-t1", order_status_normalized="paid")
    upsert_raw_order(db_session, "order-t2", order_status_normalized="paid")
    rows = [
        {"refund_event_id": "type-missing", "order_id": "order-t1", "status": 50, "refund_amount_cent": 10, "completed_at": "2026-08-01T10:00:00+08:00"},
        {"refund_event_id": "type-unknown", "order_id": "order-t2", "status": 50, "refund_type": "mystery", "refund_amount_cent": 10, "completed_at": "2026-08-01T10:00:00+08:00"},
    ]
    stats = collect_refunds(db_session, FakeRefundClient(rows), window(), source_run_id="run-type")
    assert stats.upserted == 0
    assert db_session.query(DouyinRefundEvent).count() == 0
    assert db_session.query(DataQualityIssue).filter(DataQualityIssue.issue_type == "refund_missing_type").count() == 1
    assert db_session.query(DataQualityIssue).filter(DataQualityIssue.issue_type == "refund_unknown_type").count() == 1


def test_refund_replay_uses_accepted_observation_and_occurrence_time_for_cross_month(
    db_session: Session,
) -> None:
    upsert_raw_order(db_session, "order-cross-month", order_status_normalized="paid")
    first = FakeRefundClient([
        {
            "refund_event_id": "refund-cross-month",
            "order_id": "order-cross-month",
            "status": 50,
            "refund_type": 1,
            "refund_amount_cent": 100,
            "modify_time": "2026-09-01T01:00:00+08:00",
            "completed_at": "2026-08-31T23:30:00+08:00",
        }
    ])
    collect_refunds(db_session, first, window(), source_run_id="run-new")
    stale = FakeRefundClient([
        {
            "refund_event_id": "refund-cross-month",
            "order_id": "order-cross-month",
            "status": 25,
            "refund_type": 1,
            "refund_amount_cent": 999,
            "modify_time": "2026-08-31T23:00:00+08:00",
            "completed_at": "2026-08-30T23:30:00+08:00",
        }
    ])
    collect_refunds(db_session, stale, window(), source_run_id="run-old")
    event = db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == "refund-cross-month"))
    assert event is not None
    assert event.refund_status == 2
    assert event.refund_amount_cent == 100
    assert event.occurred_at.date().isoformat() == "2026-08-31"


def test_refund_status_change_emits_deduplicated_impact_with_order_coupon_and_month_closure(
    db_session: Session,
) -> None:
    upsert_raw_order(
        db_session,
        "order-impact",
        sale_time=datetime.fromisoformat("2026-07-31T23:00:00+08:00"),
        intention_poi_id="poi-impact",
        raw_payload={},
    )
    upsert_order_coupon(
        db_session,
        "coupon-impact",
        "order-impact",
        raw_payload={},
    )
    first = FakeRefundClient([
        {
            "refund_event_id": "refund-impact",
            "order_id": "order-impact",
            "coupon_id": "coupon-impact",
            "status": 9,
            "refund_type": 1,
            "refund_amount_cent": 100,
            "apply_time": "2026-08-01T10:00:00+08:00",
            "modify_time": "2026-08-01T10:00:00+08:00",
        }
    ])
    # Processing events are valid when their applied business time is explicit.
    collect_refunds(db_session, first, window(), source_run_id="run-impact-1")
    initial = db_session.query(JobImpact).count()
    collect_refunds(db_session, first, window(), source_run_id="run-impact-2")
    assert db_session.query(JobImpact).count() == initial
    second = FakeRefundClient([
        {
            "refund_event_id": "refund-impact",
            "order_id": "order-impact",
            "coupon_id": "coupon-impact",
            "status": 50,
            "refund_type": 1,
            "refund_amount_cent": 100,
            "completed_at": "2026-08-02T10:00:00+08:00",
            "modify_time": "2026-08-02T10:00:00+08:00",
        }
    ])
    collect_refunds(db_session, second, window(), source_run_id="run-impact-3")
    impacts = list(db_session.scalars(select(JobImpact).where(JobImpact.entity_type == "refund").order_by(JobImpact.id)))
    assert len(impacts) == 2
    changed = impacts[-1]
    assert changed.affected_closure_json["order_ids"] == ["order-impact"]
    assert changed.affected_closure_json["coupon_ids"] == ["coupon-impact"]
    assert changed.affected_closure_json["sale_months"] == ["2026-07"]
    assert changed.affected_closure_json["refund_months"] == ["2026-08"]
    assert changed.affected_closure_json["affected_months"] == ["2026-07", "2026-08"]


def test_coupon_closure_keeps_sale_month_separate_from_refund_month(
    db_session: Session,
) -> None:
    upsert_raw_order(
        db_session,
        "order-coupon-month",
        sale_time=datetime.fromisoformat("2026-07-31T23:00:00+08:00"),
        raw_payload={},
    )
    upsert_order_coupon(
        db_session,
        "coupon-month",
        "order-coupon-month",
        coupon_status_normalized="verified",
        coupon_updated_at=datetime.fromisoformat("2026-08-01T10:00:00+08:00"),
        coupon_refund_time=datetime.fromisoformat("2026-09-01T10:00:00+08:00"),
        latest_refund_at=datetime.fromisoformat("2026-09-01T10:00:00+08:00"),
        raw_payload={},
        source_observed_at=datetime.fromisoformat("2026-08-01T10:00:00+08:00"),
        observation_key="coupon-month-a",
    )
    upsert_order_coupon(
        db_session,
        "coupon-month",
        "order-coupon-month",
        coupon_status_normalized="refunded",
        coupon_updated_at=datetime.fromisoformat("2026-08-02T10:00:00+08:00"),
        coupon_refund_time=datetime.fromisoformat("2026-09-01T10:00:00+08:00"),
        latest_refund_at=datetime.fromisoformat("2026-09-01T10:00:00+08:00"),
        raw_payload={},
        source_observed_at=datetime.fromisoformat("2026-08-02T10:00:00+08:00"),
        observation_key="coupon-month-b",
    )
    changed = list(
        db_session.scalars(
            select(JobImpact)
            .where(
                JobImpact.entity_type == "coupon",
                JobImpact.entity_key == "coupon-month",
            )
            .order_by(JobImpact.id)
        )
    )[-1]
    assert changed.affected_closure_json["sale_months"] == ["2026-07"]
    assert changed.affected_closure_json["refund_months"] == ["2026-09"]
    assert changed.affected_closure_json["verify_months"] == []
    assert changed.affected_closure_json["affected_months"] == ["2026-07", "2026-09"]


def test_refund_unknown_order_keeps_raw_and_retries_after_order_arrives(db_session: Session) -> None:
    payload = {
        "refund_event_id": "refund-late-order",
        "order_id": "order-late",
        "status": 50,
        "refund_type": 1,
        "refund_amount_cent": 10,
        "completed_at": "2026-08-01T10:00:00+08:00",
    }
    first_stats = collect_refunds(
        db_session,
        FakeRefundClient([payload]),
        window(),
        source_run_id="run-late-order-1",
    )
    assert first_stats.upserted == 0
    assert db_session.scalar(
        select(RawDouyinRefundRecord).where(
            RawDouyinRefundRecord.source_record_key == "refund-late-order"
        )
    ) is not None
    assert db_session.scalar(
        select(DouyinRefundEvent).where(
            DouyinRefundEvent.refund_event_id == "refund-late-order"
        )
    ) is None
    assert db_session.scalar(
        select(DataQualityIssue).where(DataQualityIssue.issue_type == "refund_unknown_order")
    ) is not None

    upsert_raw_order(db_session, "order-late", order_status_normalized="paid")
    second_stats = collect_refunds(
        db_session,
        FakeRefundClient([payload]),
        window(),
        source_run_id="run-late-order-2",
    )
    assert second_stats.upserted == 1
    assert db_session.scalar(
        select(DouyinRefundEvent).where(
            DouyinRefundEvent.refund_event_id == "refund-late-order"
        )
    ) is not None

def test_refund_explicit_coupon_must_exist_and_belong_to_order(db_session: Session) -> None:
    upsert_raw_order(db_session, "order-coupon-a", order_status_normalized="paid")
    upsert_raw_order(db_session, "order-coupon-b", order_status_normalized="paid")
    upsert_order_coupon(
        db_session,
        "coupon-b",
        "order-coupon-b",
        coupon_status_normalized="paid",
    )
    payload = {
        "refund_event_id": "refund-cross-order-coupon",
        "order_id": "order-coupon-a",
        "coupon_id": "coupon-b",
        "status": 50,
        "refund_type": 1,
        "refund_amount_cent": 20,
        "completed_at": "2026-08-01T10:00:00+08:00",
    }
    stats = collect_refunds(
        db_session,
        FakeRefundClient([payload]),
        window(),
        source_run_id="run-cross-order-coupon",
    )
    assert stats.upserted == 0
    assert db_session.scalar(
        select(DouyinRefundEvent).where(
            DouyinRefundEvent.refund_event_id == "refund-cross-order-coupon"
        )
    ) is None
    assert db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type == "refund_coupon_order_mismatch"
        )
    ) is not None


def test_refund_stable_id_cannot_move_to_a_different_order(db_session: Session) -> None:
    upsert_raw_order(db_session, "order-stable-a", order_status_normalized="paid")
    upsert_raw_order(db_session, "order-stable-b", order_status_normalized="paid")
    first = {
        "refund_event_id": "refund-stable-order",
        "order_id": "order-stable-a",
        "status": 50,
        "refund_type": 1,
        "refund_amount_cent": 30,
        "completed_at": "2026-08-01T10:00:00+08:00",
        "modify_time": "2026-08-01T11:00:00+08:00",
    }
    collect_refunds(db_session, FakeRefundClient([first]), window(), source_run_id="run-stable-a")
    conflict = {
        **first,
        "order_id": "order-stable-b",
        "refund_amount_cent": 999,
        "modify_time": "2026-08-02T11:00:00+08:00",
    }
    stats = collect_refunds(
        db_session,
        FakeRefundClient([conflict]),
        window(),
        source_run_id="run-stable-b",
    )
    assert stats.upserted == 0
    raw = db_session.scalar(
        select(RawDouyinRefundRecord).where(
            RawDouyinRefundRecord.source_record_key == "refund-stable-order"
        )
    )
    event = db_session.scalar(
        select(DouyinRefundEvent).where(
            DouyinRefundEvent.refund_event_id == "refund-stable-order"
        )
    )
    assert raw is not None and raw.order_id == "order-stable-a"
    assert (
        event is not None
        and event.order_id == "order-stable-a"
        and event.refund_amount_cent == 30
    )
    assert db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type == "refund_stable_id_order_conflict"
        )
    ) is not None


def test_refund_ambiguous_amount_unit_is_dqi_only(db_session: Session) -> None:
    upsert_raw_order(db_session, "order-ambiguous-unit", order_status_normalized="paid")
    payload = {
        "refund_event_id": "refund-ambiguous-unit",
        "order_id": "order-ambiguous-unit",
        "status": 50,
        "refund_type": 1,
        "refund_amount": 1234,
        "completed_at": "2026-08-01T10:00:00+08:00",
    }
    stats = collect_refunds(
        db_session,
        FakeRefundClient([payload]),
        window(),
        source_run_id="run-ambiguous-unit",
    )
    assert stats.upserted == 0
    assert db_session.scalar(
        select(DouyinRefundEvent).where(
            DouyinRefundEvent.refund_event_id == "refund-ambiguous-unit"
        )
    ) is None
    assert db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type == "refund_amount_unit_ambiguous"
        )
    ) is not None


@pytest.mark.parametrize("unrelated_amount_key", ["platform_fee_cent", "shipping_fee_cent"])
def test_refund_unrelated_cent_fields_are_not_refund_amount(
    db_session: Session,
    unrelated_amount_key: str,
) -> None:
    order_id = f"order-unrelated-{unrelated_amount_key}"
    refund_id = f"refund-unrelated-{unrelated_amount_key}"
    upsert_raw_order(db_session, order_id, order_status_normalized="paid")
    payload = {
        "refund_event_id": refund_id,
        "order_id": order_id,
        "status": 50,
        "refund_type": 1,
        unrelated_amount_key: 777,
        "completed_at": "2026-08-01T10:00:00+08:00",
    }
    stats = collect_refunds(
        db_session,
        FakeRefundClient([payload]),
        window(),
        source_run_id=f"run-{refund_id}",
    )
    assert stats.upserted == 0
    assert db_session.scalar(
        select(RawDouyinRefundRecord).where(
            RawDouyinRefundRecord.source_record_key == refund_id
        )
    ) is not None
    assert db_session.scalar(
        select(DouyinRefundEvent).where(
            DouyinRefundEvent.refund_event_id == refund_id
        )
    ) is None
    assert db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type == "refund_missing_amount",
            DataQualityIssue.order_id == order_id,
        )
    ) is not None


def test_refund_nested_unrelated_cent_field_is_not_refund_amount(db_session: Session) -> None:
    order_id = "order-nested-unrelated-fee"
    refund_id = "refund-nested-unrelated-fee"
    upsert_raw_order(db_session, order_id, order_status_normalized="paid")
    payload = {
        "refund_event_id": refund_id,
        "order_id": order_id,
        "status": 50,
        "refund_type": 1,
        "fees": {"shipping_fee_cent": 777},
        "completed_at": "2026-08-01T10:00:00+08:00",
    }
    stats = collect_refunds(
        db_session,
        FakeRefundClient([payload]),
        window(),
        source_run_id="run-refund-nested-unrelated-fee",
    )
    assert stats.upserted == 0
    assert db_session.scalar(
        select(DouyinRefundEvent).where(
            DouyinRefundEvent.refund_event_id == refund_id
        )
    ) is None
    assert db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type == "refund_missing_amount",
            DataQualityIssue.order_id == order_id,
        )
    ) is not None


def test_refund_query_has_more_true_without_cursor_fails_date_phase(db_session: Session) -> None:
    class MissingCursorClient:
        def query_refunds(self, start: datetime, end: datetime, *, cursor=None, page_size: int = 100):
            _ = (start, end, cursor, page_size)
            return {"data": {"refunds": [], "has_more": True}}

    with pytest.raises(RefundCollectionError, match="cursor"):
        collect_refunds(
            db_session,
            MissingCursorClient(),
            window(),
            source_run_id="run-refund-missing-cursor",
        )
    assert db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type == "refund_cursor_nonadvance"
        )
    ) is not None
