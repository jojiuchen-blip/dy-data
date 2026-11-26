"""DYDATA-115 task, actual-time attribution and global self-volume contracts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import load_only

from apps.api.dy_api.clue_followup_metrics import (
    AssignmentRoundEvidence, ClueFollowUpEvidence, FollowUpEvidence,
)
from apps.api.dy_api.clue_task_metrics import (
    _evaluate_order,
    load_clue_task_facts,
    load_self_store_verifications,
    load_store_task_totals,
)
from apps.api.dy_api.clue_task_metrics_sources import (
    OrderProductClassification, jingcheng_order_predicate, load_order_product_classifications,
)
from apps.api.dy_api.clue_verification_facts import enrich_verification_facts
from apps.api.dy_api.models import (
    ClueAssignmentRound, ClueCenterOrder, ClueFollowUpRecord, ClueMasterLead, ClueOrderStatusEvent,
    DimSkuProductRule, DimStore, DimStorePoiMapping, RawDouyinClue,
    RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinRefundRecord, RawDouyinVerifyRecord,
)


AT = datetime(2026, 11, 16, 16, tzinfo=timezone.utc)  # China Nov 17 midnight.
CUTOFF = AT + timedelta(days=10)


def _order(session, order_id="O", *, scope="精诚养车", product_type="精诚养车"):
    sku = "sku-" + order_id
    session.add(DimSkuProductRule(sku_id=sku, product_id="product-" + order_id,
                                 product_scope=scope, product_type=product_type))
    session.add(RawDouyinOrder(order_id=order_id, sku_id=sku, order_status_normalized="active",
                               source_observed_at=AT, updated_at=AT))
    session.flush()
    return order_id


def _task(session, task_id="R", *, order_id="O", store="A", hour=0, mode="formal",
          status="active_unfollowed", handoff=None, matured=None):
    row = ClueAssignmentRound(
        assignment_round_id=task_id, order_id=order_id, round_no=int(hour) + 1,
        assigned_store_id=store, assigned_at=AT + timedelta(hours=hour),
        round_status=status, execution_mode=mode, first_follow_up_sla_hours=48,
        reassigned_at=AT + timedelta(hours=handoff) if handoff is not None else None,
        matured_at=AT + timedelta(hours=matured) if matured is not None else None,
        created_at=AT, updated_at=AT,
    )
    session.add(row)
    return row


def _follow(session, record_id="F", *, task="R", order_id="O", store="A", hour=1,
            result="further_follow_up", deleted=False, operator=None):
    session.add(ClueFollowUpRecord(
        follow_up_record_id=record_id, order_id=order_id, assignment_round_id=task,
        assigned_store_id=store, round_no=1, follow_result=result,
        created_at=AT + timedelta(hours=hour), deleted_at=AT if deleted else None,
        operator_user_id=operator,
    ))


def _verify(session, verify_id="V", *, order_id="O", store="A", hour=2,
            observed_hour=None, cancel_hour=None, status="success", coupon_id=None):
    if session.get(DimStore, store) is None:
        session.add(DimStore(store_id=store, store_name="Store " + store))
        session.add(DimStorePoiMapping(poi_id="poi-" + store, store_id=store))
        session.flush()
    coupon_id = coupon_id or "coupon-" + verify_id
    if session.scalar(select(RawDouyinOrderCoupon).where(RawDouyinOrderCoupon.coupon_id == coupon_id)) is None:
        session.add(RawDouyinOrderCoupon(coupon_id=coupon_id, order_id=order_id,
                                         source_observed_at=AT))
        session.flush()
    session.add(RawDouyinVerifyRecord(
        verify_id=verify_id, coupon_id=coupon_id, verify_status=status,
        verify_time=AT + timedelta(hours=hour), poi_id="poi-" + store,
        source_observed_at=AT + timedelta(hours=observed_hour if observed_hour is not None else hour),
        cancel_time=AT + timedelta(hours=cancel_hour) if cancel_hour is not None else None,
    ))


def _close_lead(session, *, order_id="O", hour=10, reason="no_candidate"):
    session.add(ClueMasterLead(
        lead_key="lead-" + order_id, order_id=order_id,
        source_clue_row_key="source-" + order_id, source_identity_key="identity-" + order_id,
        lifecycle_status="closed", normalized_order_status="active",
        closed_at=AT + timedelta(hours=hour), closed_reason=reason, created_at=AT, updated_at=AT,
    ))


@pytest.mark.parametrize(("detected_hour", "follow_hour", "assigned_hour", "operator", "handoff", "expected"), [
    (27, 12, 0, "staff", None, 1),
    (27, 24, 0, "staff", None, 1),
    (27, 25, 0, "staff", None, 0),
    (12, 12, 0, "staff", None, 0),
    (10, 12, 0, "staff", None, 0),
    (None, 12, 0, "staff", None, 0),
    (27, 12, 0, None, None, 0),
    (27, 12, 0, "staff", 11, 0),
    (27, 12, -420, "staff", None, 0),  # China Oct 30, with its own 24h window.
])
def test_credit_record_submitted_before_verification_was_observed(
    db_session, detected_hour, follow_hour, assigned_hour, operator, handoff, expected,
):
    _order(db_session)
    verify_hour = assigned_hour + 6
    _close_lead(db_session, hour=verify_hour, reason="order_verified")
    db_session.flush()
    row = _task(db_session, hour=0, status="closed_order_verified", handoff=handoff)
    row.assigned_at = AT + timedelta(hours=assigned_hour)
    row.lead_key = "lead-O"
    row.closed_at = AT + timedelta(hours=verify_hour)
    _verify(db_session, store="B", hour=verify_hour, observed_hour=assigned_hour + (detected_hour or 27))
    _follow(db_session, hour=assigned_hour + follow_hour, operator=operator)
    if detected_hour is not None:
        detected = AT + timedelta(hours=assigned_hour + detected_hour)
        db_session.add(ClueOrderStatusEvent(
            event_id="sync", event_key="sync", order_id="O", lead_key="lead-O",
            normalized_status="verified", status_source="coupon", observed_at=detected, created_at=detected,
        ))
    db_session.commit()

    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert (fact.follow_24h_numerator, fact.follow_any_numerator, fact.follow_denominator) == (expected, expected, 1)
    assert fact.verification_numerator == 0
    assert fact.verification_facts[0].had_valid_follow_before_verify is False
    assert bool(fact.pre_sync_follow_record_ids) is bool(expected)
    if detected_hour is None:
        assert fact.reason_code == "pre_sync_observation_missing"


def test_fixed_24_hours_is_independent_of_sla_and_duplicate_records(db_session):
    _order(db_session)
    _task(db_session)
    _follow(db_session, hour=30)
    _follow(db_session, "repeat", hour=31)
    _follow(db_session, "wrong-store", store="B", hour=1)
    _follow(db_session, "deleted", deleted=True)
    _follow(db_session, "view", result="pending")
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert (fact.follow_24h_numerator, fact.follow_any_numerator, fact.follow_denominator) == (0, 1, 1)
    assert fact.follow_record_ids == ()
    assert fact.follow_any_record_ids == ("F", "repeat")


@pytest.mark.parametrize("result", ["continue_following", "success", "failed"])
@pytest.mark.parametrize("hour,expected_fast", [(1, 1), (30, 0)])
def test_historical_schema_supported_manual_records_keep_fixed_window_counts(db_session, result, hour, expected_fast):
    _order(db_session)
    _task(db_session)
    _follow(db_session, result=result, hour=hour)
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert (fact.follow_24h_numerator, fact.follow_any_numerator, fact.follow_denominator) == (expected_fast, 1, 1)
    assert fact.follow_any_record_ids == ("F",)
    assert fact.verification_numerator == 0  # a historical success record is not a source verification


@pytest.mark.parametrize("invalid", ["deleted", "wrong-store", "wrong-task", "before", "after-close", "unknown-value"])
def test_historical_labels_do_not_bypass_record_validity(db_session, invalid):
    _order(db_session)
    row = _task(db_session)
    if invalid == "after-close":
        row.closed_at = AT + timedelta(hours=2)
    _follow(db_session, result="need_follow_up" if invalid == "unknown-value" else "continue_following",
            deleted=invalid == "deleted", store="B" if invalid == "wrong-store" else "A",
            task="another-task" if invalid == "wrong-task" else "R",
            hour=-1 if invalid == "before" else 3 if invalid == "after-close" else 1)
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert fact.follow_24h_numerator == fact.follow_any_numerator == 0
    assert fact.follow_denominator == 1


def test_historical_success_record_at_its_projected_close_is_a_manual_submission(db_session):
    _order(db_session)
    row = _task(db_session, status="closed_order_verified")
    row.closed_at = row.verified_at = AT + timedelta(hours=2)
    row.verified_store_id = "A"
    _follow(db_session, result="success", hour=2)
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert (fact.follow_24h_numerator, fact.follow_any_numerator, fact.follow_denominator) == (1, 1, 1)
    assert fact.verification_numerator == 0
    assert load_self_store_verifications(db_session, ["O"], observed_through=CUTOFF) == ()


def test_historical_failed_record_that_closes_its_task_counts_once(db_session):
    _order(db_session)
    row = _task(db_session, status="closed_lost")
    row.closed_at = AT + timedelta(hours=2)
    _close_lead(db_session, hour=2, reason="failed")
    _follow(db_session, result="failed", hour=2)
    _follow(db_session, "late-failed", result="failed", hour=3)
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert fact.follow_any_record_ids == ("F",)
    assert (fact.follow_24h_numerator, fact.follow_any_numerator, fact.follow_denominator) == (1, 1, 1)


def test_historical_projection_flags_without_a_manual_record_do_not_count(db_session):
    _order(db_session)
    row = _task(db_session)
    row.follow_result = "continue_following"
    row.is_followed = row.is_follow_success = True
    row.followed_at = AT + timedelta(hours=1)
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert fact.follow_24h_numerator == fact.follow_any_numerator == 0
    assert fact.follow_denominator == 1


@pytest.mark.parametrize("result", ["success", "failed"])
@pytest.mark.parametrize("terminal", ["verified", "refunded", "closed"])
def test_actual_order_terminal_at_same_instant_precedes_historical_label(db_session, result, terminal):
    _order(db_session)
    row = _task(db_session, status="closed_order_verified" if terminal == "verified" else "closed_order")
    row.closed_at = AT + timedelta(hours=2)
    _follow(db_session, result=result, hour=2)
    if terminal == "verified":
        row.verified_at, row.verified_store_id = row.closed_at, "A"
        _verify(db_session, hour=2)
    else:
        order = db_session.scalar(select(RawDouyinOrder))
        order.order_status_normalized = terminal
        order.raw_payload = {"refund_completed_at" if terminal == "refunded" else "closed_at": row.closed_at.isoformat()}
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert fact.follow_24h_numerator == fact.follow_any_numerator == 0
    assert fact.follow_denominator == (1 if terminal == "verified" else 0)
    if terminal == "verified":
        assert fact.verification_numerator == 1
        assert fact.verification_facts[0].had_valid_follow_before_verify is False


def test_early_self_verification_does_not_create_manual_follow(db_session):
    _order(db_session)
    row = _task(db_session)
    _verify(db_session)
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert (fact.follow_24h_numerator, fact.follow_any_numerator, fact.follow_denominator) == (0, 0, 1)
    assert (fact.verification_numerator, fact.verification_denominator) == (1, 1)
    assert fact.verification_facts[0].had_valid_follow_before_verify is False
    assert len(load_self_store_verifications(db_session, ["O"], observed_through=CUTOFF)) == 1
    db_session.refresh(row)
    assert row.verified_at is None and row.is_followed is False


@pytest.mark.parametrize("terminal,has_follow,expected", [
    ("refunded", False, (0, 0, 0)), ("refunded", True, (1, 1, 1)),
    ("closed", False, (0, 0, 0)), ("closed", True, (1, 1, 1)),
    ("partial", False, (0, 0, 1)), ("requested", False, (0, 0, 1)),
])
def test_early_refund_or_invalid_excludes_only_without_valid_submission(db_session, terminal, has_follow, expected):
    _order(db_session)
    _task(db_session)
    if has_follow:
        _follow(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    if terminal in {"refunded", "closed"}:
        order.order_status_normalized = terminal
        order.raw_payload = {"refund_completed_at" if terminal == "refunded" else "closed_at":
                             (AT + timedelta(hours=4)).isoformat()}
    else:
        db_session.add(RawDouyinRefundRecord(
            source_record_key="refund", refund_id="refund", order_id="O",
            normalized_refund_status=2 if terminal == "partial" else 1,
            refund_completed_at=AT + timedelta(hours=4), source_observed_at=AT + timedelta(hours=4),
            payload_hash="hash", raw_payload={"refund_type": "1"},
        ))
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert (fact.follow_24h_numerator, fact.follow_any_numerator, fact.follow_denominator) == expected
    assert fact.verification_denominator == 1


def test_first_actual_time_owns_late_ingest_before_a_later_handoff(db_session):
    _order(db_session)
    _task(db_session, "A0", status="expired_pending_reassign", handoff=24)
    _task(db_session, "B1", store="B", hour=24)
    _verify(db_session, hour=20, observed_hour=30)
    db_session.commit()
    before = load_clue_task_facts(db_session, ["O"], observed_through=AT + timedelta(hours=29))
    assert sum(fact.verification_numerator for fact in before.values()) == 0
    after = load_clue_task_facts(db_session, ["O"], observed_through=AT + timedelta(hours=31))
    assert after["A0"].verification_numerator == 1
    assert after["B1"].verification_numerator == 0
    assert after["A0"].verification_facts[0].effective_assignment_round_id == "A0"
    assert db_session.get(ClueAssignmentRound, "B1").round_status == "active_unfollowed"


def test_active_other_store_verification_never_backcredits_previous_task(db_session):
    _order(db_session)
    _task(db_session, "A0", status="expired_pending_reassign", handoff=24)
    _task(db_session, "B1", store="B", hour=24)
    _verify(db_session, "first", hour=25)
    db_session.commit()
    facts = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)
    assert [facts[key].verification_numerator for key in ("A0", "B1")] == [0, 0]
    detail = facts["A0"].verification_facts[0]
    assert detail.effective_assignment_round_id == "B1"
    assert detail.credited_assignment_round_id is None
    assert detail.is_back_credit is False
    assert len(facts["A0"].verification_facts) == 1


def test_later_coupon_after_overall_close_can_independently_backcredit_prior_task(db_session):
    _order(db_session)
    _task(db_session, "A0", status="expired_pending_reassign", handoff=24)
    _task(db_session, "B1", store="B", hour=24)
    _verify(db_session, "during-B", hour=25)
    _verify(db_session, "after-close", hour=50)
    _verify(db_session, "another-after-close", hour=51)
    db_session.commit()
    facts = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)
    assert [facts[key].verification_numerator for key in ("A0", "B1")] == [1, 0]
    first, later, repeated = facts["A0"].verification_facts
    assert first.effective_assignment_round_id == "B1" and first.credited_assignment_round_id is None
    assert first.is_back_credit is False and first.is_after_close is False
    assert later.effective_assignment_round_id is None and later.credited_assignment_round_id == "A0"
    assert later.is_after_close and later.is_back_credit and later.counts_for_store_verification_rate
    assert repeated.credited_assignment_round_id == "A0"  # task numerator remains at most one
    other_task_later = facts["B1"].verification_facts[1]
    assert other_task_later.is_back_credit and other_task_later.credited_assignment_round_id == "A0"
    assert other_task_later.counts_for_store_verification_rate is False
    self_volume = load_self_store_verifications(db_session, ["O"], observed_through=CUTOFF)
    assert len(self_volume) == 1
    assert self_volume[0].verify_id == "during-B" and self_volume[0].business_date == date(2026, 11, 18)


@pytest.mark.parametrize("close_reason", ["no_candidate", "natural_expiry", "lost", "request_store_change"])
def test_verification_after_overall_close_backcredits_original_store(db_session, close_reason):
    _order(db_session)
    _task(db_session, "A0", status="expired_pending_reassign", handoff=24)
    _task(db_session, "B1", store="B", hour=24, status="closed_no_candidate", handoff=48)
    _close_lead(db_session, hour=48, reason=close_reason)
    _follow(db_session, task="A0")
    _verify(db_session, hour=50, observed_hour=80)
    db_session.commit()
    facts = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)
    assert (facts["A0"].verification_numerator, facts["B1"].verification_numerator) == (1, 0)
    detail = facts["A0"].verification_facts[0]
    assert detail.is_back_credit and detail.is_after_close and detail.had_valid_follow_before_verify
    assert detail.credited_assignment_round_id == "A0" and detail.effective_assignment_round_id is None
    rows = [{"order_id": "O", "assignment_round_id": "A0", "assigned_store_id": "A"}]
    enrich_verification_facts(db_session, rows, CUTOFF)
    assert rows[0]["verification_summary"] == "关单后核销"
    assert rows[0]["verification_facts"][0]["credited_assignment_round_id"] == "A0"


def test_verification_before_first_task_counts_only_self_store_volume(db_session):
    _order(db_session)
    _task(db_session, hour=20)
    _verify(db_session, hour=1)
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert fact.verification_numerator == 0
    assert fact.verification_denominator == 1
    assert fact.verification_facts == ()
    assert len(load_self_store_verifications(db_session, ["O"], observed_through=CUTOFF)) == 1


def test_first_self_store_date_is_global_before_report_filter_and_no_task_is_required(db_session):
    _order(db_session)
    _verify(db_session, "nov17", hour=1)
    _verify(db_session, "nov18", hour=25)
    _verify(db_session, "other-store", store="B", hour=26)
    db_session.commit()
    facts = load_self_store_verifications(db_session, ["O"], observed_through=CUTOFF)
    assert [(row.store_id, row.verify_id, row.business_date) for row in facts] == [
        ("A", "nov17", date(2026, 11, 17)), ("B", "other-store", date(2026, 11, 18)),
    ]
    assert [row for row in facts if row.store_id == "A" and row.business_date == date(2026, 11, 18)] == []
    assert len([row for row in facts if row.store_id == "A" and row.business_date.month == 11]) == 1
    assert load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF) == {}


def test_cancellation_and_reverification_recompute_first_effective_date(db_session):
    _order(db_session)
    _task(db_session)
    _verify(db_session, "canceled", hour=1, cancel_hour=3)
    _verify(db_session, "valid-reverify", hour=25, coupon_id="coupon-canceled")
    _verify(db_session, "failed", hour=0, status="failed")
    db_session.commit()
    earlier = load_self_store_verifications(db_session, ["O"], observed_through=AT + timedelta(hours=2))
    assert earlier[0].verify_id == "canceled"
    now = load_self_store_verifications(db_session, ["O"], observed_through=CUTOFF)
    assert now[0].verify_id == "valid-reverify" and now[0].business_date == date(2026, 11, 18)
    assert load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"].verification_numerator == 1


def test_unmapped_poi_never_guesses_a_store(db_session):
    _order(db_session)
    _task(db_session)
    _verify(db_session)
    db_session.flush()
    db_session.get(RawDouyinVerifyRecord, "V").poi_id = "unmapped-poi"
    db_session.commit()
    assert load_self_store_verifications(db_session, ["O"], observed_through=CUTOFF) == ()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert fact.verification_numerator == 0
    assert fact.verification_facts[0].verified_store_id is None


def test_trial_unassigned_and_storeless_tasks_do_not_enter_task_denominators(db_session):
    _order(db_session)
    _task(db_session, "formal")
    _task(db_session, "trial", mode="trial", store="B", hour=1)
    _task(db_session, "storeless", store=None, hour=2)
    unassigned = _task(db_session, "unassigned", hour=3)
    unassigned.assigned_at = None
    _follow(db_session, task="trial", store="B")
    db_session.commit()
    assert set(load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)) == {"formal"}


@pytest.mark.parametrize("source", ["order-sku", "raw-product", "raw-sku", "center-product", "center-sku", "unknown"])
def test_marketing_partition_keeps_three_source_membership_and_precise_type(db_session, source):
    db_session.add(DimSkuProductRule(sku_id="JC", product_id="P", product_scope="精诚养车", product_type="268保养"))
    db_session.add(RawDouyinOrder(order_id="O", sku_id="JC" if source == "order-sku" else None,
                                  source_observed_at=AT, updated_at=AT))
    if source.startswith("raw-"):
        db_session.add(RawDouyinClue(clue_row_key="source", clue_id="C", order_id="O",
                                     product_id="P" if source == "raw-product" else "JC"))
    if source.startswith("center-"):
        db_session.add(ClueCenterOrder(order_id="O", lead_status="active", current_round_status="unassigned",
                                       product_id="P" if source == "center-product" else "JC"))
    _task(db_session)
    db_session.commit()
    classification = load_order_product_classifications(db_session, ["O"])["O"]
    assert classification.is_jingcheng is (source != "unknown")
    assert classification.product_scope == ("byd" if source == "unknown" else "jingcheng")
    if source != "unknown":
        assert classification.product_type == "268保养"
    selected = db_session.scalars(select(ClueAssignmentRound.order_id).where(
        jingcheng_order_predicate(ClueAssignmentRound.order_id),
    )).all()
    assert selected == (["O"] if source != "unknown" else [])


def test_allocation_totals_use_merged_counts_and_exclude_byd_samples(db_session):
    _order(db_session, "JC")
    _task(db_session, "jc", order_id="JC")
    _verify(db_session, order_id="JC")
    _order(db_session, "BYD", scope="比亚迪本品", product_type="保养")
    _task(db_session, "byd", order_id="BYD")
    _follow(db_session, order_id="BYD", task="byd")
    db_session.commit()
    jc = load_store_task_totals(db_session, ["A", "empty"], AT, CUTOFF, observed_through=CUTOFF)
    all_types = load_store_task_totals(db_session, ["A"], AT, CUTOFF, product_scope="all", observed_through=CUTOFF)
    assert (jc["A"].conversion_numerator, jc["A"].conversion_denominator,
            jc["A"].follow_24h_numerator, jc["A"].follow_24h_denominator) == (1, 1, 0, 1)
    assert (all_types["A"].conversion_numerator, all_types["A"].conversion_denominator,
            all_types["A"].follow_24h_numerator, all_types["A"].follow_24h_denominator) == (1, 2, 1, 2)
    assert jc["empty"].conversion_denominator == 0


def test_real_closed_at_fences_manual_submissions_while_matured_is_not_a_close():
    row = AssignmentRoundEvidence("R", "O", 1, "A", AT, round_status="closed_lost",
                                   closed_at=AT + timedelta(hours=2))
    records = (FollowUpEvidence("lost", "O", "R", "A", AT + timedelta(hours=2), follow_result="lost"),
               FollowUpEvidence("late", "O", "R", "A", AT + timedelta(hours=3), follow_result="appointment"))
    evidence = ClueFollowUpEvidence("O", rounds=(row,), follow_ups_by_round={"R": records})
    facts = _evaluate_order(evidence, events=(), classification=OrderProductClassification("O", None, False),
                             lead_closes=(), cutoff=CUTOFF)
    assert facts["R"].follow_any_record_ids == ("lost",)
    assert facts["R"].closed_at == row.closed_at


def test_matured_at_does_not_end_an_actual_task(db_session):
    _order(db_session)
    _task(db_session, matured=1)
    _follow(db_session, hour=2)
    _verify(db_session, hour=3)
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert (fact.follow_any_numerator, fact.verification_numerator) == (1, 1)


def test_known_early_full_refund_precedes_a_later_verification(db_session):
    _order(db_session)
    _task(db_session)
    db_session.add(RawDouyinRefundRecord(
        source_record_key="full-refund", refund_id="full-refund", order_id="O",
        normalized_refund_status=2, refund_completed_at=AT + timedelta(hours=4),
        source_observed_at=AT + timedelta(hours=4), payload_hash="hash",
        raw_payload={"refund_type": "2"},
    ))
    _verify(db_session, hour=10)
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert fact.terminal_kind == "refunded" and fact.terminal_at == AT + timedelta(hours=4)
    assert (fact.follow_denominator, fact.follow_any_numerator) == (0, 0)
    assert fact.verification_numerator == 1
    assert fact.verification_facts[0].is_back_credit


def test_follow_at_or_after_actual_terminal_cannot_count_even_if_ingested_late(db_session):
    _order(db_session)
    _task(db_session)
    _follow(db_session, "at-terminal", hour=4)
    _follow(db_session, "after-terminal", hour=5)
    _verify(db_session, hour=4, observed_hour=12)
    db_session.commit()
    before = load_clue_task_facts(db_session, ["O"], observed_through=AT + timedelta(hours=6))["R"]
    assert before.follow_any_numerator == 1
    after = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert after.follow_any_numerator == after.follow_24h_numerator == 0
    assert after.follow_denominator == 1


def test_exact_handoff_time_belongs_to_new_task(db_session):
    _order(db_session)
    _task(db_session, "A0", status="expired_pending_reassign", handoff=24)
    _task(db_session, "B1", store="B", hour=24)
    _follow(db_session, "old-at-handoff", task="A0", hour=24)
    _verify(db_session, store="B", hour=24)
    db_session.commit()
    facts = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)
    assert facts["A0"].verification_numerator == facts["A0"].follow_any_numerator == 0
    assert facts["B1"].verification_numerator == 1
    assert facts["B1"].verification_facts[0].effective_assignment_round_id == "B1"


def test_unknown_terminal_business_time_cannot_invent_early_exclusion(db_session):
    _order(db_session)
    _task(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    order.order_status_normalized = "refunded"
    db_session.commit()
    fact = load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF)["R"]
    assert fact.reason_code == "terminal_time_unknown"
    assert fact.follow_denominator == 1 and fact.verification_denominator == 1


def test_trial_projection_cannot_create_a_self_store_verification(db_session):
    _order(db_session)
    trial = _task(db_session, mode="trial")
    trial.verified_at = AT + timedelta(hours=2)
    trial.verified_store_id = "A"
    trial.is_self_store_verified = True
    db_session.commit()
    assert load_clue_task_facts(db_session, ["O"], observed_through=CUTOFF) == {}
    assert load_self_store_verifications(db_session, ["O"], observed_through=CUTOFF) == ()


def test_allocation_cohort_window_is_half_open_and_history_credit_is_stable(db_session):
    _order(db_session)
    _task(db_session, "A0", status="expired_pending_reassign", handoff=24)
    _task(db_session, "B1", store="B", hour=24, status="closed_no_candidate", handoff=48)
    _close_lead(db_session, hour=48)
    _verify(db_session, hour=50)
    db_session.commit()
    first_day = load_store_task_totals(db_session, ["A", "B"], AT, AT + timedelta(hours=24),
                                        product_scope="all", observed_through=CUTOFF)
    second_day = load_store_task_totals(db_session, ["A", "B"], AT + timedelta(hours=24), AT + timedelta(hours=48),
                                         product_scope="all", observed_through=CUTOFF)
    assert (first_day["A"].conversion_numerator, first_day["A"].conversion_denominator) == (1, 1)
    assert first_day["B"].conversion_denominator == 0
    assert second_day["A"].conversion_denominator == 0
    assert (second_day["B"].conversion_numerator, second_day["B"].conversion_denominator) == (0, 1)


def test_bulk_task_facts_have_constant_queries_per_identifier_batch(db_session):
    for index in range(12):
        order_id = "O-" + str(index)
        _order(db_session, order_id)
        _task(db_session, "R-" + str(index), order_id=order_id)
    db_session.commit()
    statements = []
    bind = db_session.get_bind()

    def capture(_connection, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(bind, "before_cursor_execute", capture)
    try:
        one = load_clue_task_facts(db_session, ["O-0"], observed_through=CUTOFF)
        one_count = len(statements)
        statements.clear()
        many = load_clue_task_facts(db_session, ["O-" + str(index) for index in range(12)], observed_through=CUTOFF)
        assert len(statements) == one_count
        assert len(one) == 1 and len(many) == 12
    finally:
        event.remove(bind, "before_cursor_execute", capture)


def test_catalog_resolution_is_joined_to_only_requested_order_sources(db_session):
    _order(db_session, "selected")
    for index in range(8):
        _order(db_session, "unrelated-" + str(index), scope="比亚迪本品", product_type="保养")
    db_session.commit()
    captured = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if "dim_sku_product_rules" in statement:
            captured.append((statement, parameters))

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = load_order_product_classifications(db_session, ["selected"])
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    assert set(result) == {"selected"}
    assert result["selected"].is_jingcheng
    assert len(captured) == 1
    statement, parameters = captured[0]
    assert all(source + ".order_id IN" in statement for source in (
        "raw_douyin_orders", "raw_douyin_clues", "clue_center_orders",
    ))
    assert "JOIN (SELECT" in statement and "UNION" in statement
    assert parameters == ("selected", "selected", "selected")


def test_additive_evidence_metadata_respects_legacy_raiseload_projection(db_session):
    _order(db_session)
    _task(db_session)
    _follow(db_session)
    db_session.commit()
    db_session.expunge_all()
    round_row = db_session.scalar(select(ClueAssignmentRound).options(load_only(
        ClueAssignmentRound.assignment_round_id, ClueAssignmentRound.order_id,
        ClueAssignmentRound.round_no, ClueAssignmentRound.assigned_store_id,
        ClueAssignmentRound.assigned_at, ClueAssignmentRound.execution_mode,
        ClueAssignmentRound.verified_store_id, ClueAssignmentRound.verified_at,
        ClueAssignmentRound.updated_at, raiseload=True,
    )))
    follow_row = db_session.scalar(select(ClueFollowUpRecord).options(load_only(
        ClueFollowUpRecord.follow_up_record_id, ClueFollowUpRecord.order_id,
        ClueFollowUpRecord.assignment_round_id, ClueFollowUpRecord.assigned_store_id,
        ClueFollowUpRecord.created_at, ClueFollowUpRecord.deleted_at, raiseload=True,
    )))
    statements = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", capture)
    try:
        round_evidence = AssignmentRoundEvidence.from_row(round_row)
        follow_evidence = FollowUpEvidence.from_row(follow_row)
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    assert round_evidence.assignment_round_id == "R" and round_evidence.assigned_store_id == "A"
    assert round_evidence.closed_at is None and round_evidence.round_status is None
    assert follow_evidence.follow_result is None
    assert statements == []  # conversion never triggers a lazy SELECT


def test_allocation_filters_product_scope_before_loading_order_histories(db_session, monkeypatch):
    import apps.api.dy_api.clue_task_metrics as task_metrics

    _order(db_session, "JC")
    _task(db_session, "JC-task", order_id="JC")
    _order(db_session, "BYD", scope="比亚迪本品", product_type="保养")
    _task(db_session, "BYD-task", order_id="BYD")
    db_session.commit()
    loaded = []
    original = task_metrics.load_clue_task_facts

    def capture(session, order_ids, **kwargs):
        selected = set(order_ids)
        loaded.append(selected)
        return original(session, selected, **kwargs)

    monkeypatch.setattr(task_metrics, "load_clue_task_facts", capture)
    task_metrics.load_store_task_totals(db_session, ["A"], AT, CUTOFF, product_scope="jingcheng", observed_through=CUTOFF)
    task_metrics.load_store_task_totals(db_session, ["A"], AT, CUTOFF, product_scope="byd", observed_through=CUTOFF)
    task_metrics.load_store_task_totals(db_session, ["A"], AT, CUTOFF, product_scope="all", observed_through=CUTOFF)
    assert loaded == [{"JC"}, {"BYD"}, {"JC", "BYD"}]
