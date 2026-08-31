from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueMaterializationWorkItem,
    DataQualityIssue,
    JobAttempt,
    JobImpact,
    RawDouyinClue,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
)
from apps.worker.repositories import (
    begin_clue_materialization_cycle,
    claim_clue_materialization_batch,
    complete_clue_materialization_batch,
    renew_clue_materialization_batch,
    retry_clue_materialization_batch,
    upsert_order_coupon,
    upsert_raw_order,
    upsert_raw_clue,
    upsert_verify_record,
    upsert_store,
    upsert_store_poi_mapping,
)


def test_same_business_order_with_new_run_and_payload_has_no_new_impact(
    db_session: Session,
) -> None:
    upsert_raw_order(
        db_session,
        "order-1",
        order_status="paid",
        order_status_raw="paid",
        order_status_normalized="paid",
        paid_amount_cent=1000,
        order_paid_amount_cent=1000,
        intention_poi_id="poi-1",
        source_run_id="run-1",
        payload_fingerprint="a" * 64,
        raw_payload={"run": 1},
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="order-1:2026-08-01T00:00:00Z",
    )
    first_count = db_session.query(JobImpact).count()

    upsert_raw_order(
        db_session,
        "order-1",
        order_status="paid",
        order_status_raw="paid",
        order_status_normalized="paid",
        paid_amount_cent=1000,
        order_paid_amount_cent=1000,
        intention_poi_id="poi-1",
        source_run_id="run-2",
        payload_fingerprint="b" * 64,
        raw_payload={"run": 2, "request_id": "different"},
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="order-1:2026-08-01T00:00:00Z",
    )

    assert first_count == 1
    assert db_session.query(JobImpact).count() == 1
    assert db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-1")).source_run_id == "run-2"


def test_raw_label_only_changes_do_not_emit_business_impacts(db_session: Session) -> None:
    upsert_raw_order(
        db_session,
        "order-label-only",
        order_status="paid",
        order_status_raw="paid",
        order_status_normalized="paid",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="order-label-1",
    )
    before_coupon = db_session.query(JobImpact).count()
    upsert_raw_order(
        db_session,
        "order-label-only",
        order_status="success",
        order_status_raw="SUCCESS",
        order_status_normalized="paid",
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="order-label-2",
    )
    assert db_session.query(JobImpact).count() == before_coupon

    upsert_order_coupon(
        db_session,
        "coupon-label-only",
        "order-label-only",
        coupon_status="fulfilled",
        coupon_status_raw="fulfilled",
        coupon_status_normalized="verified",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="coupon-label-1",
    )
    after_coupon_insert = db_session.query(JobImpact).count()
    upsert_order_coupon(
        db_session,
        "coupon-label-only",
        "order-label-only",
        coupon_status="used",
        coupon_status_raw="USED",
        coupon_status_normalized="verified",
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="coupon-label-2",
    )
    assert db_session.query(JobImpact).count() == after_coupon_insert


def test_clue_and_verify_synonym_labels_do_not_emit_projection_impacts(
    db_session: Session,
) -> None:
    upsert_raw_clue(
        db_session,
        "clue-synonym",
        clue_id="clue-synonym",
        order_status="履约中",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="clue-synonym-1",
    )
    clue_count = db_session.query(JobImpact).count()
    upsert_raw_clue(
        db_session,
        "clue-synonym",
        clue_id="clue-synonym",
        order_status="201",
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="clue-synonym-2",
    )
    assert db_session.query(JobImpact).count() == clue_count

    upsert_verify_record(
        db_session,
        "verify-synonym",
        verify_status="valid",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="verify-synonym-1",
    )
    verify_count = db_session.query(JobImpact).count()
    upsert_verify_record(
        db_session,
        "verify-synonym",
        verify_status="verified",
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="verify-synonym-2",
    )
    assert db_session.query(JobImpact).count() == verify_count


def test_repeated_later_a_b_a_b_observations_each_emit_distinct_impacts(
    db_session: Session,
) -> None:
    for index, (status, key) in enumerate(
        (("paid", "a1"), ("refunded", "b1"), ("paid", "a2"), ("refunded", "b2")),
        start=1,
    ):
        upsert_raw_order(
            db_session,
            "order-cycle",
            order_status_normalized=status,
            source_observed_at=datetime(2026, 8, index, tzinfo=timezone.utc),
            observation_key=key,
        )

    impacts = list(
        db_session.scalars(
            select(JobImpact)
            .where(JobImpact.entity_type == "order")
            .order_by(JobImpact.id)
        )
    )
    assert len(impacts) == 4
    assert impacts[0].change_kind == "insert"
    assert [impact.new_values_json["order_status_normalized"] for impact in impacts] == [
        "paid",
        "refunded",
        "paid",
        "refunded",
    ]


def test_business_change_records_before_after_and_impact_closure(db_session: Session) -> None:
    upsert_store(db_session, "store-old", "Old")
    upsert_store(db_session, "store-new", "New")
    upsert_store_poi_mapping(db_session, "store-old", "poi-old")
    upsert_store_poi_mapping(db_session, "store-new", "poi-new")
    upsert_raw_order(
        db_session,
        "order-1",
        order_status_normalized="paid",
        paid_amount_cent=1000,
        order_paid_amount_cent=1000,
        intention_poi_id="poi-old",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="a",
    )
    upsert_raw_order(
        db_session,
        "order-1",
        order_status_normalized="refunded",
        paid_amount_cent=900,
        order_paid_amount_cent=900,
        intention_poi_id="poi-new",
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="b",
    )

    impacts = list(db_session.scalars(select(JobImpact).order_by(JobImpact.id)))
    order_impacts = [impact for impact in impacts if impact.entity_type == "order"]
    assert len(order_impacts) == 2
    changed = order_impacts[-1]
    assert changed.old_values_json["order_status_normalized"] == "paid"
    assert changed.new_values_json["order_status_normalized"] == "refunded"
    assert changed.affected_closure_json["order_ids"] == ["order-1"]
    assert changed.affected_closure_json["poi_ids"] == ["poi-new", "poi-old"]
    assert changed.affected_closure_json["store_ids"] == ["store-new", "store-old"]


def test_store_poi_mapping_change_emits_old_and_new_store_impact(
    db_session: Session,
) -> None:
    upsert_store(db_session, "store-a", "A")
    upsert_store(db_session, "store-b", "B")
    upsert_store_poi_mapping(
        db_session,
        "store-a",
        "poi-switch",
        mapping_source="initial",
    )
    upsert_store_poi_mapping(
        db_session,
        "store-a",
        "poi-switch",
        mapping_source="replayed-audit-label",
    )
    upsert_store_poi_mapping(db_session, "store-b", "poi-switch")

    impacts = list(
        db_session.scalars(
            select(JobImpact)
            .where(JobImpact.entity_type == "store_poi_mapping")
            .order_by(JobImpact.id)
        )
    )
    assert len(impacts) == 2
    changed = impacts[-1]
    assert changed.old_values_json["store_id"] == "store-a"
    assert changed.new_values_json["store_id"] == "store-b"
    assert changed.affected_closure_json["poi_ids"] == ["poi-switch"]
    assert changed.affected_closure_json["store_ids"] == ["store-a", "store-b"]


def test_store_poi_mapping_a_b_a_b_keeps_every_real_transition_and_replay_is_idempotent(
    db_session: Session,
) -> None:
    upsert_store(db_session, "store-loop-a", "A")
    upsert_store(db_session, "store-loop-b", "B")
    transitions = ("store-loop-a", "store-loop-b", "store-loop-a", "store-loop-b")
    for index, store_id in enumerate(transitions):
        kwargs = {
            "source_run_id": f"mapping-run-{index // 2}",
            "payload_fingerprint": f"mapping-fingerprint-{index}",
            "observation_key": f"mapping-run-{index // 2}:poi-loop:{index}",
        }
        upsert_store_poi_mapping(db_session, store_id, "poi-loop", **kwargs)
        if index in {1, 3}:
            upsert_store_poi_mapping(db_session, store_id, "poi-loop", **kwargs)

    impacts = list(
        db_session.scalars(
            select(JobImpact)
            .where(
                JobImpact.entity_type == "store_poi_mapping",
                JobImpact.entity_key == "poi-loop",
            )
            .order_by(JobImpact.id)
        )
    )
    assert [impact.new_values_json["store_id"] for impact in impacts] == [
        "store-loop-a",
        "store-loop-b",
        "store-loop-a",
        "store-loop-b",
    ]


def test_clue_contact_change_emits_non_pii_impact(db_session: Session) -> None:
    upsert_raw_clue(
        db_session,
        "clue-pii",
        clue_id="clue-pii",
        name="Alice Secret",
        telephone="13800138000",
        enc_telephone="cipher-a",
        author_nickname="Alice Author",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="clue-pii-a",
        raw_payload={"telephone": "13800138000"},
    )
    upsert_raw_clue(
        db_session,
        "clue-pii",
        clue_id="clue-pii",
        name="Bob Secret",
        telephone="13900139000",
        enc_telephone="cipher-b",
        author_nickname="Bob Author",
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="clue-pii-b",
        raw_payload={"telephone": "13900139000"},
    )
    impact = db_session.scalar(
        select(JobImpact)
        .where(JobImpact.entity_type == "clue", JobImpact.entity_key == "clue-pii")
        .order_by(JobImpact.id.desc())
    )
    assert impact is not None
    encoded = repr({"old": impact.old_values_json, "new": impact.new_values_json})
    for secret in ("Alice Secret", "Bob Secret", "13800138000", "13900139000", "cipher-a", "cipher-b", "Alice Author", "Bob Author"):
        assert secret not in encoded
    for sensitive_key in ("name", "telephone", "enc_telephone", "author_nickname"):
        assert sensitive_key not in impact.old_values_json
        assert sensitive_key not in impact.new_values_json
    assert impact.old_values_json["contact_identity_digest"] != impact.new_values_json["contact_identity_digest"]


def test_clue_closure_resolves_all_old_and_new_follow_intention_poi_stores(
    db_session: Session,
) -> None:
    poi_store_pairs = (
        ("poi-follow-old", "store-follow-old"),
        ("poi-intention-old", "store-intention-old"),
        ("poi-follow-new", "store-follow-new"),
        ("poi-intention-new", "store-intention-new"),
    )
    for poi_id, store_id in poi_store_pairs:
        upsert_store(db_session, store_id, store_id)
        upsert_store_poi_mapping(db_session, store_id, poi_id)

    upsert_raw_clue(
        db_session,
        "clue-four-pois",
        clue_id="clue-four-pois",
        follow_poi_id="poi-follow-old",
        intention_poi_id="poi-intention-old",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="clue-four-pois-a",
    )
    upsert_raw_clue(
        db_session,
        "clue-four-pois",
        clue_id="clue-four-pois",
        follow_poi_id="poi-follow-new",
        intention_poi_id="poi-intention-new",
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="clue-four-pois-b",
    )
    changed = list(
        db_session.scalars(
            select(JobImpact)
            .where(
                JobImpact.entity_type == "clue",
                JobImpact.entity_key == "clue-four-pois",
            )
            .order_by(JobImpact.id)
        )
    )[-1]
    assert changed.affected_closure_json["poi_ids"] == [
        "poi-follow-new",
        "poi-follow-old",
        "poi-intention-new",
        "poi-intention-old",
    ]
    assert changed.affected_closure_json["store_ids"] == [
        "store-follow-new",
        "store-follow-old",
        "store-intention-new",
        "store-intention-old",
    ]


def test_older_replay_cannot_regress_current_observation(db_session: Session) -> None:
    upsert_raw_order(
        db_session,
        "order-1",
        order_status_normalized="refunded",
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="new",
        raw_payload={"status": "new"},
        payload_fingerprint="n" * 64,
    )
    upsert_raw_order(
        db_session,
        "order-1",
        order_status_normalized="paid",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="old",
        raw_payload={"status": "old"},
        payload_fingerprint="o" * 64,
        source_run_id="old-run",
    )
    row = db_session.get(RawDouyinOrder, db_session.scalar(select(RawDouyinOrder.id).where(RawDouyinOrder.order_id == "order-1")))
    assert row is not None
    assert row.order_status_normalized == "refunded"
    assert row.raw_payload == {"status": "new"}
    assert row.observation_key == "new"


def test_legacy_order_metadata_bootstrap_rejects_old_and_accepts_new_observation(
    db_session: Session,
) -> None:
    lower_bound = datetime(2026, 8, 1, tzinfo=timezone.utc)
    legacy = upsert_raw_order(
        db_session,
        "legacy-order-observation",
        order_status_normalized="refunded",
        source_observed_at=None,
        observation_key=None,
    )
    legacy.created_at = lower_bound
    legacy.updated_at = lower_bound
    db_session.flush()
    before_count = db_session.query(JobImpact).filter(JobImpact.entity_type == "order").count()

    upsert_raw_order(
        db_session,
        "legacy-order-observation",
        order_status_normalized="paid",
        source_observed_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        observation_key="legacy-order-old",
    )
    assert legacy.order_status_normalized == "refunded"
    assert legacy.source_observed_at is None
    assert legacy.observation_key is None
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "order").count() == before_count

    upsert_raw_order(
        db_session,
        "legacy-order-observation",
        order_status_normalized="paid",
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="legacy-order-new",
    )
    assert legacy.order_status_normalized == "paid"
    assert legacy.source_observed_at == datetime(2026, 8, 2, tzinfo=timezone.utc)
    assert legacy.observation_key == "legacy-order-new"
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "order").count() == before_count + 1


def test_legacy_clue_metadata_bootstrap_uses_business_time_boundary(
    db_session: Session,
) -> None:
    lower_bound = datetime(2026, 8, 1, tzinfo=timezone.utc)
    legacy = upsert_raw_clue(
        db_session,
        "legacy-clue-observation",
        clue_id="legacy-clue",
        order_status="refunded",
        modify_time=lower_bound,
        source_observed_at=None,
        observation_key=None,
    )
    legacy.imported_at = lower_bound
    legacy.updated_at = lower_bound
    db_session.flush()
    before_count = db_session.query(JobImpact).filter(JobImpact.entity_type == "clue").count()

    upsert_raw_clue(
        db_session,
        "legacy-clue-observation",
        clue_id="legacy-clue",
        order_status="verified",
        source_observed_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        observation_key="legacy-clue-old",
    )
    assert legacy.order_status == "refunded"
    assert legacy.source_observed_at is None
    assert legacy.observation_key is None
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "clue").count() == before_count

    upsert_raw_clue(
        db_session,
        "legacy-clue-observation",
        clue_id="legacy-clue",
        order_status="verified",
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="legacy-clue-new",
    )
    assert legacy.order_status == "verified"
    assert legacy.source_observed_at == datetime(2026, 8, 2, tzinfo=timezone.utc)
    assert legacy.observation_key == "legacy-clue-new"
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "clue").count() == before_count + 1


def test_legacy_coupon_metadata_bootstrap_uses_coupon_and_parent_order_time(
    db_session: Session,
) -> None:
    lower_bound = datetime(2026, 8, 1, tzinfo=timezone.utc)
    order = upsert_raw_order(
        db_session,
        "legacy-coupon-order",
        order_status_normalized="paid",
        source_observed_at=None,
        observation_key=None,
    )
    order.created_at = lower_bound
    order.updated_at = lower_bound
    db_session.flush()
    legacy = upsert_order_coupon(
        db_session,
        "legacy-coupon-observation",
        "legacy-coupon-order",
        coupon_status_normalized="refunded",
        coupon_updated_at=lower_bound,
        source_observed_at=None,
        observation_key=None,
    )
    before_count = db_session.query(JobImpact).filter(JobImpact.entity_type == "coupon").count()

    upsert_order_coupon(
        db_session,
        "legacy-coupon-observation",
        "legacy-coupon-order",
        coupon_status_normalized="verified",
        coupon_updated_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        source_observed_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        observation_key="legacy-coupon-old",
    )
    assert legacy.coupon_status_normalized == "refunded"
    assert legacy.source_observed_at is None
    assert legacy.observation_key is None
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "coupon").count() == before_count

    upsert_order_coupon(
        db_session,
        "legacy-coupon-observation",
        "legacy-coupon-order",
        coupon_status_normalized="verified",
        coupon_updated_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="legacy-coupon-new",
    )
    assert legacy.coupon_status_normalized == "verified"
    assert legacy.source_observed_at == datetime(2026, 8, 2, tzinfo=timezone.utc)
    assert legacy.observation_key == "legacy-coupon-new"
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "coupon").count() == before_count + 1


def test_legacy_verify_metadata_bootstrap_uses_verify_time_boundary(
    db_session: Session,
) -> None:
    lower_bound = datetime(2026, 8, 1, tzinfo=timezone.utc)
    legacy = upsert_verify_record(
        db_session,
        "legacy-verify-observation",
        verify_status="valid",
        verify_time=lower_bound,
        source_observed_at=None,
        observation_key=None,
    )
    before_count = db_session.query(JobImpact).filter(JobImpact.entity_type == "verify").count()

    upsert_verify_record(
        db_session,
        "legacy-verify-observation",
        verify_status="cancelled",
        verify_time=datetime(2026, 7, 31, tzinfo=timezone.utc),
        source_observed_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        observation_key="legacy-verify-old",
    )
    assert legacy.verify_status == "valid"
    assert legacy.source_observed_at is None
    assert legacy.observation_key is None
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "verify").count() == before_count

    upsert_verify_record(
        db_session,
        "legacy-verify-observation",
        verify_status="cancelled",
        verify_time=datetime(2026, 8, 2, tzinfo=timezone.utc),
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="legacy-verify-new",
    )
    assert legacy.verify_status == "cancelled"
    assert legacy.source_observed_at == datetime(2026, 8, 2, tzinfo=timezone.utc)
    assert legacy.observation_key == "legacy-verify-new"
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "verify").count() == before_count + 1


def test_coupon_order_conflict_keeps_existing_row_and_records_idempotent_dqi(
    db_session: Session,
) -> None:
    order_a = upsert_raw_order(
        db_session,
        "coupon-conflict-order-a",
        order_status_normalized="paid",
    )
    order_b = upsert_raw_order(
        db_session,
        "coupon-conflict-order-b",
        order_status_normalized="paid",
    )
    coupon = upsert_order_coupon(
        db_session,
        "coupon-conflict",
        "coupon-conflict-order-a",
        coupon_status_normalized="available",
        raw_payload={"version": "a"},
        source_run_id="coupon-run-a",
        payload_fingerprint="a" * 64,
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="coupon-conflict-a",
    )
    before_impacts = db_session.query(JobImpact).filter(JobImpact.entity_type == "coupon").count()

    conflict_values = {
        "coupon_status_normalized": "verified",
        "raw_payload": {"version": "b"},
        "source_run_id": "coupon-run-b",
        "payload_fingerprint": "b" * 64,
        "source_observed_at": datetime(2026, 8, 2, tzinfo=timezone.utc),
        "observation_key": "coupon-conflict-b",
    }
    conflicting = upsert_order_coupon(
        db_session,
        "coupon-conflict",
        "coupon-conflict-order-b",
        **conflict_values,
    )
    assert conflicting is coupon
    assert coupon.order_id == order_a.order_id == "coupon-conflict-order-a"
    assert coupon.raw_order_id == order_a.id
    assert coupon.coupon_status_normalized == "available"
    assert coupon.raw_payload == {"version": "a"}
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "coupon").count() == before_impacts

    issue = db_session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.issue_type == "coupon_order_conflict",
            DataQualityIssue.coupon_id == "coupon-conflict",
        )
    )
    assert issue is not None
    assert issue.severity == "error"
    assert issue.raw_context_json == {
        "coupon_id": "coupon-conflict",
        "existing_order_id": "coupon-conflict-order-a",
        "incoming_order_id": "coupon-conflict-order-b",
        "existing_raw_order_id": order_a.id,
        "incoming_raw_order_id": order_b.id,
        "payload_fingerprint": "b" * 64,
        "source_run_id": "coupon-run-b",
    }

    upsert_order_coupon(
        db_session,
        "coupon-conflict",
        "coupon-conflict-order-b",
        **conflict_values,
    )
    assert db_session.query(DataQualityIssue).filter(
        DataQualityIssue.issue_type == "coupon_order_conflict",
        DataQualityIssue.coupon_id == "coupon-conflict",
    ).count() == 1
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "coupon").count() == before_impacts

    upsert_order_coupon(
        db_session,
        "coupon-conflict",
        "coupon-conflict-order-a",
        coupon_status_normalized="verified",
        raw_payload={"version": "a2"},
        source_run_id="coupon-run-a2",
        payload_fingerprint="a2" * 32,
        source_observed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        observation_key="coupon-conflict-a2",
    )
    assert coupon.order_id == "coupon-conflict-order-a"
    assert coupon.coupon_status_normalized == "verified"
    assert coupon.raw_payload == {"version": "a2"}
    assert db_session.query(JobImpact).filter(JobImpact.entity_type == "coupon").count() == before_impacts + 1


def test_equal_timestamp_observations_choose_the_same_lexical_winner_in_any_order(
    db_session: Session,
) -> None:
    observed = datetime(2026, 8, 1, tzinfo=timezone.utc)
    upsert_raw_order(
        db_session,
        "order-a",
        order_status_normalized="paid",
        source_observed_at=observed,
        observation_key="z-key",
    )
    upsert_raw_order(
        db_session,
        "order-a",
        order_status_normalized="refunded",
        source_observed_at=observed,
        observation_key="a-key",
    )
    upsert_raw_order(
        db_session,
        "order-b",
        order_status_normalized="refunded",
        source_observed_at=observed,
        observation_key="a-key",
    )
    upsert_raw_order(
        db_session,
        "order-b",
        order_status_normalized="paid",
        source_observed_at=observed,
        observation_key="z-key",
    )
    a = db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-a"))
    b = db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-b"))
    assert a is not None and b is not None
    assert a.order_status_normalized == b.order_status_normalized == "paid"
    assert a.observation_key == b.observation_key == "z-key"


def test_clue_coupon_and_verify_business_changes_emit_closures_but_audit_only_does_not(
    db_session: Session,
) -> None:
    observed = datetime(2026, 8, 1, tzinfo=timezone.utc)
    upsert_raw_order(db_session, "order-1", order_status_normalized="paid", source_observed_at=observed, observation_key="o")
    upsert_raw_clue(db_session, "clue-row", clue_id="clue-1", order_id="order-1", follow_poi_id="poi-1", source_observed_at=observed, observation_key="c", source_run_id="run-1", raw_payload={"v": 1})
    first = db_session.query(JobImpact).count()
    upsert_raw_clue(db_session, "clue-row", clue_id="clue-1", order_id="order-1", follow_poi_id="poi-1", source_observed_at=observed, observation_key="c", source_run_id="run-2", raw_payload={"v": 2})
    assert db_session.query(JobImpact).count() == first
    upsert_order_coupon(db_session, "coupon-1", "order-1", coupon_status_normalized="available", source_observed_at=observed, observation_key="cp-1", raw_payload={"v": 1})
    upsert_order_coupon(db_session, "coupon-1", "order-1", coupon_status_normalized="verified", source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc), observation_key="cp-2", raw_payload={"v": 2})
    upsert_verify_record(db_session, "verify-1", coupon_id="coupon-1", verify_status="valid", poi_id="poi-1", source_observed_at=observed, observation_key="v-1", raw_payload={"v": 1})
    upsert_verify_record(db_session, "verify-1", coupon_id="coupon-1", verify_status="cancelled", poi_id="poi-2", source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc), observation_key="v-2", raw_payload={"v": 2})
    impacts = list(db_session.scalars(select(JobImpact).order_by(JobImpact.id)))
    assert any(item.entity_type == "coupon" and item.affected_closure_json["coupon_ids"] == ["coupon-1"] for item in impacts)
    verify_change = [item for item in impacts if item.entity_type == "verify"][-1]
    assert verify_change.affected_closure_json["poi_ids"] == ["poi-1", "poi-2"]


def test_verify_insert_closure_resolves_coupon_order_sale_month_and_store(
    db_session: Session,
) -> None:
    sale_time = datetime(2026, 7, 15, 10, tzinfo=timezone.utc)
    upsert_store(db_session, "store-sale", "Sale Store")
    upsert_store(db_session, "store-verify", "Verify Store")
    upsert_store_poi_mapping(db_session, "store-sale", "poi-sale")
    upsert_store_poi_mapping(db_session, "store-verify", "poi-verify")
    upsert_raw_order(
        db_session,
        "order-v",
        order_status_normalized="paid",
        sale_time=sale_time,
        intention_poi_id="poi-sale",
        source_observed_at=sale_time,
        observation_key="order-v",
    )
    upsert_order_coupon(db_session, "coupon-v", "order-v")

    upsert_verify_record(
        db_session,
        "verify-v",
        coupon_id="coupon-v",
        verify_status="valid",
        poi_id="poi-verify",
        verify_time=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
        source_observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        observation_key="verify-v-1",
    )

    impact = db_session.scalar(
        select(JobImpact)
        .where(JobImpact.entity_type == "verify", JobImpact.entity_key == "verify-v")
        .order_by(JobImpact.id.desc())
    )
    assert impact is not None
    closure = impact.affected_closure_json
    assert closure["order_ids"] == ["order-v"]
    assert closure["sale_months"] == ["2026-07"]
    assert closure["poi_ids"] == ["poi-sale", "poi-verify"]
    assert closure["store_ids"] == ["store-sale", "store-verify"]
    assert closure["verify_months"] == ["2026-08"]
    assert closure["affected_months"] == ["2026-07", "2026-08"]


def test_verify_coupon_order_change_closure_keeps_old_and_new_order_chains(
    db_session: Session,
) -> None:
    order_facts = (
        (
            "order-a",
            "coupon-a",
            datetime(2026, 6, 15, 10, tzinfo=timezone.utc),
            "poi-intention-a",
            "store-intention-a",
        ),
        (
            "order-b",
            "coupon-b",
            datetime(2026, 7, 15, 10, tzinfo=timezone.utc),
            "poi-intention-b",
            "store-intention-b",
        ),
    )
    for order_id, coupon_id, sale_time, intention_poi_id, store_id in order_facts:
        upsert_store(db_session, store_id, store_id)
        upsert_store_poi_mapping(db_session, store_id, intention_poi_id)
        upsert_raw_order(
            db_session,
            order_id,
            order_status_normalized="paid",
            sale_time=sale_time,
            intention_poi_id=intention_poi_id,
            source_observed_at=sale_time,
            observation_key=order_id,
        )
        upsert_order_coupon(db_session, coupon_id, order_id)
    upsert_store(db_session, "store-verify-old", "Verify Old")
    upsert_store(db_session, "store-verify-new", "Verify New")
    upsert_store_poi_mapping(db_session, "store-verify-old", "poi-verify-old")
    upsert_store_poi_mapping(db_session, "store-verify-new", "poi-verify-new")

    upsert_verify_record(
        db_session,
        "verify-switch",
        coupon_id="coupon-a",
        verify_status="valid",
        poi_id="poi-verify-old",
        verify_time=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
        source_observed_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        observation_key="verify-switch-a",
    )
    upsert_verify_record(
        db_session,
        "verify-switch",
        coupon_id="coupon-b",
        verify_status="valid",
        poi_id="poi-verify-new",
        verify_time=datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
        source_observed_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        observation_key="verify-switch-b",
    )

    impact = db_session.scalar(
        select(JobImpact)
        .where(JobImpact.entity_type == "verify", JobImpact.entity_key == "verify-switch")
        .order_by(JobImpact.id.desc())
    )
    assert impact is not None
    closure = impact.affected_closure_json
    assert closure["order_ids"] == ["order-a", "order-b"]
    assert closure["sale_months"] == ["2026-06", "2026-07"]
    assert closure["poi_ids"] == [
        "poi-intention-a",
        "poi-intention-b",
        "poi-verify-new",
        "poi-verify-old",
    ]
    assert closure["store_ids"] == [
        "store-intention-a",
        "store-intention-b",
        "store-verify-new",
        "store-verify-old",
    ]
    assert closure["verify_months"] == ["2026-08"]
    assert closure["affected_months"] == ["2026-06", "2026-07", "2026-08"]


def test_frozen_cycle_does_not_consume_impacts_created_after_upper_bound(
    db_session: Session,
) -> None:
    for order_id in ("order-1", "order-2"):
        upsert_raw_order(
            db_session,
            order_id,
            order_status_normalized="paid",
            source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            observation_key=order_id,
        )

    checkpoint = begin_clue_materialization_cycle(db_session, scope="test")
    first_upper_bound = checkpoint.frozen_upper_bound_id
    assert first_upper_bound > 0
    with pytest.raises(ValueError, match="lease_token"):
        claim_clue_materialization_batch(
            db_session,
            scope="test",
            limit=1,
            lease_token=" ",
        )
    upsert_raw_order(
        db_session,
        "order-3",
        order_status_normalized="paid",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="order-3",
    )

    first = claim_clue_materialization_batch(
        db_session,
        scope="test",
        limit=10,
        lease_token="attempt-test-first",
    )
    assert [item.entity_key for item in first] == ["order-1", "order-2"]
    assert (
        claim_clue_materialization_batch(
            db_session,
            scope="test",
            limit=10,
            lease_token="attempt-test-first",
        )
        == []
    )
    assert (
        retry_clue_materialization_batch(
            db_session,
            [item.work_item_id for item in first],
            lease_token="clue-worker:wrong-attempt",
        )
        == 0
    )
    assert retry_clue_materialization_batch(
        db_session,
        [item.work_item_id for item in first],
        lease_token="attempt-test-first",
    ) == len(first)
    retry = claim_clue_materialization_batch(
        db_session,
        scope="test",
        limit=10,
        lease_token="attempt-test-reclaim",
    )
    assert [item.entity_key for item in retry] == ["order-1", "order-2"]

    complete_clue_materialization_batch(
        db_session,
        [item.work_item_id for item in retry],
        lease_token="attempt-test-reclaim",
    )
    next_checkpoint = begin_clue_materialization_cycle(db_session, scope="test")
    assert next_checkpoint.frozen_upper_bound_id > first_upper_bound
    second = claim_clue_materialization_batch(
        db_session,
        scope="test",
        limit=10,
        lease_token="attempt-test-second",
    )
    assert [item.entity_key for item in second] == ["order-3"]


def test_expired_processing_item_is_reclaimed_and_begin_resumes_original_bound(
    db_session: Session,
) -> None:
    upsert_raw_order(
        db_session,
        "order-crash",
        order_status_normalized="paid",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="crash",
    )
    checkpoint = begin_clue_materialization_cycle(db_session, scope="lease")
    claimed = claim_clue_materialization_batch(
        db_session,
        scope="lease",
        lease_token="clue-worker:attempt-a",
        lease_seconds=1,
    )
    assert len(claimed) == 1
    resumed = begin_clue_materialization_cycle(db_session, scope="lease")
    assert resumed.cycle_id == checkpoint.cycle_id
    claimed[0].lease_expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.flush()
    reclaimed = claim_clue_materialization_batch(
        db_session,
        scope="lease",
        lease_token="clue-worker:attempt-b",
    )
    assert [item.entity_key for item in reclaimed] == ["order-crash"]
    assert (
        complete_clue_materialization_batch(
            db_session,
            [item.work_item_id for item in reclaimed],
            lease_token="clue-worker:attempt-a",
        )
        == 0
    )
    assert (
        complete_clue_materialization_batch(
            db_session,
            [item.work_item_id for item in reclaimed],
            lease_token="clue-worker:attempt-b",
        )
        == 1
    )


def _persist_materialization_attempt(
    db_session: Session,
    *,
    attempt_id: str,
    finished_at: datetime | None,
) -> None:
    started_at = (finished_at or datetime.now(timezone.utc)) - timedelta(seconds=1)
    db_session.add(
        JobAttempt(
            attempt_id=attempt_id,
            job_id=f"job-for-{attempt_id}",
            stage_run_id=None,
            attempt_number=1,
            lease_epoch=1,
            component_type="worker",
            component_instance_id=f"component-for-{attempt_id}",
            started_at=started_at,
            finished_at=finished_at,
            exit_type="crashed" if finished_at is not None else None,
            created_at=started_at,
        )
    )
    db_session.flush()


def test_finished_attempt_reclaims_future_materialization_lease_immediately(
    db_session: Session,
) -> None:
    """A durable finished attempt must make its still-future item reclaimable."""

    upsert_raw_order(
        db_session,
        "order-finished-attempt-reclaim",
        order_status_normalized="paid",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="finished-attempt-reclaim",
    )
    begin_clue_materialization_cycle(db_session, scope="finished-attempt")
    first = claim_clue_materialization_batch(
        db_session,
        scope="finished-attempt",
        lease_token="attempt-a-finished",
        lease_seconds=300,
    )
    assert len(first) == 1
    _persist_materialization_attempt(
        db_session,
        attempt_id="attempt-a-finished",
        finished_at=datetime.now(timezone.utc),
    )
    db_session.commit()

    replacement = claim_clue_materialization_batch(
        db_session,
        scope="finished-attempt",
        lease_token="attempt-b-recovery",
        lease_seconds=300,
    )
    assert [item.work_item_id for item in replacement] == [first[0].work_item_id]
    assert (
        complete_clue_materialization_batch(
            db_session,
            [first[0].work_item_id],
            lease_token="attempt-a-finished",
        )
        == 0
    )
    assert (
        renew_clue_materialization_batch(
            db_session,
            [first[0].work_item_id],
            lease_token="attempt-a-finished",
            lease_seconds=300,
        )
        == 0
    )
    assert (
        complete_clue_materialization_batch(
            db_session,
            [first[0].work_item_id],
            lease_token="attempt-b-recovery",
        )
        == 1
    )


def test_unfinished_attempt_keeps_future_materialization_lease_unclaimable(
    db_session: Session,
) -> None:
    """A live attempt must remain the sole owner until expiry or completion."""

    upsert_raw_order(
        db_session,
        "order-active-attempt-reclaim",
        order_status_normalized="paid",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="active-attempt-reclaim",
    )
    begin_clue_materialization_cycle(db_session, scope="active-attempt")
    first = claim_clue_materialization_batch(
        db_session,
        scope="active-attempt",
        lease_token="attempt-a-active",
        lease_seconds=300,
    )
    assert len(first) == 1
    _persist_materialization_attempt(
        db_session,
        attempt_id="attempt-a-active",
        finished_at=None,
    )
    db_session.commit()

    assert (
        claim_clue_materialization_batch(
            db_session,
            scope="active-attempt",
            lease_token="attempt-b-blocked",
            lease_seconds=300,
        )
        == []
    )


def test_expired_owner_cannot_complete_before_takeover(
    db_session: Session,
) -> None:
    upsert_raw_order(
        db_session,
        "order-expired-before-takeover",
        order_status_normalized="paid",
        source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        observation_key="expired-before-takeover",
    )
    begin_clue_materialization_cycle(db_session, scope="fence")
    claimed = claim_clue_materialization_batch(
        db_session,
        scope="fence",
        lease_token="clue-worker:attempt-a-fence",
        lease_seconds=300,
    )
    assert len(claimed) == 1
    claimed[0].lease_expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.flush()

    # The original owner is fenced as soon as the DB-clock lease expires,
    # even if no replacement worker has claimed the item yet.
    assert (
        complete_clue_materialization_batch(
            db_session,
            [claimed[0].work_item_id],
            lease_token="clue-worker:attempt-a-fence",
        )
        == 0
    )
    replacement = claim_clue_materialization_batch(
        db_session,
        scope="fence",
        lease_token="clue-worker:attempt-b-fence",
    )
    assert len(replacement) == 1
    assert (
        complete_clue_materialization_batch(
            db_session,
            [replacement[0].work_item_id],
            lease_token="clue-worker:attempt-b-fence",
        )
        == 1
    )


def test_cursor_advances_only_after_contiguous_completed_items(db_session: Session) -> None:
    for order_id in ("order-gap-a", "order-gap-b"):
        upsert_raw_order(
            db_session,
            order_id,
            order_status_normalized="paid",
            source_observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            observation_key=order_id,
        )
    begin_clue_materialization_cycle(db_session, scope="gap")
    batch = claim_clue_materialization_batch(
        db_session,
        scope="gap",
        limit=2,
        lease_token="attempt-gap",
    )
    assert len(batch) == 2
    assert (
        complete_clue_materialization_batch(
            db_session,
            [batch[1].work_item_id],
            lease_token="attempt-gap",
        )
        == 1
    )
    checkpoint = begin_clue_materialization_cycle(db_session, scope="gap")
    assert checkpoint.last_work_item_id == 0
    assert (
        complete_clue_materialization_batch(
            db_session,
            [batch[0].work_item_id],
            lease_token="attempt-gap",
        )
        == 1
    )
    assert db_session.get(type(checkpoint), "gap").last_work_item_id == max(item.work_item_id for item in batch)
