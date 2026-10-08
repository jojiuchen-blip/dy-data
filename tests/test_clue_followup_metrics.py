from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.api.dy_api.clue_followup_metrics import (
    AssignmentRoundEvidence,
    CLUE_FOLLOWUP_METRIC_DEFINITIONS,
    FollowUpEvidence,
    TerminalEvidence,
    bulk_evaluate_clue_followup_metrics,
    evaluate_clue_followup_round,
    load_clue_followup_evidence,
    load_terminal_evidence,
)
from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueFollowUpRecord,
    DimSkuProductRule,
    RawDouyinClue,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinRefundRecord,
    RawDouyinVerifyRecord,
    SettlementOrderDetail,
)


AT = datetime(2026, 10, 1, 0, tzinfo=timezone.utc)
CUTOFF = AT + timedelta(hours=6)


def round_value(*, round_id: str = "R", order_id: str = "O", assigned_at: datetime | None = AT) -> AssignmentRoundEvidence:
    return AssignmentRoundEvidence(
        assignment_round_id=round_id,
        order_id=order_id,
        round_no=1,
        assigned_store_id="STORE-A",
        assigned_at=assigned_at,
    )


def follow(*, record_id: str = "F", created_at: datetime = AT + timedelta(hours=1), deleted_at: datetime | None = None) -> FollowUpEvidence:
    return FollowUpEvidence(
        follow_up_record_id=record_id,
        order_id="O",
        assignment_round_id="R",
        assigned_store_id="STORE-A",
        created_at=created_at,
        deleted_at=deleted_at,
    )


@pytest.mark.parametrize(
    ("name", "terminal", "follows", "cutoff", "expected"),
    [
        ("assigned under 24h", None, (), CUTOFF, (0, 1, "active_under_observation")),
        (
            "assignment after observation cutoff",
            None,
            (),
            AT - timedelta(minutes=1),
            (0, 0, "assignment_after_observation_cutoff"),
        ),
        (
            "terminal before assignment",
            TerminalEvidence("refunded", AT - timedelta(minutes=1), AT),
            (),
            CUTOFF,
            (0, 0, "terminal_before_assignment"),
        ),
        (
            "early verified without follow",
            TerminalEvidence("verified", AT + timedelta(hours=4), AT + timedelta(hours=4)),
            (),
            CUTOFF,
            (1, 1, "verified_within_24h"),
        ),
        (
            "terminal time unknown",
            TerminalEvidence("verified", None, AT + timedelta(hours=4)),
            (follow(),),
            CUTOFF,
            (0, 0, "terminal_time_unknown"),
        ),
        (
            "early refund with follow",
            TerminalEvidence("refunded", AT + timedelta(hours=4), AT + timedelta(hours=4)),
            (follow(),),
            CUTOFF,
            (1, 1, "terminal_within_24h_followed"),
        ),
        (
            "early refund without follow",
            TerminalEvidence("refunded", AT + timedelta(hours=4), AT + timedelta(hours=4)),
            (),
            CUTOFF,
            (0, 0, "terminal_within_24h_unfollowed"),
        ),
        (
            "deleted follow",
            None,
            (follow(deleted_at=AT + timedelta(hours=2)),),
            CUTOFF,
            (0, 1, "active_under_observation"),
        ),
        (
            "post terminal follow",
            TerminalEvidence("refunded", AT + timedelta(hours=3), AT + timedelta(hours=3)),
            (follow(created_at=AT + timedelta(hours=4)),),
            CUTOFF,
            (0, 0, "terminal_within_24h_unfollowed"),
        ),
        (
            "terminal beyond 24h",
            TerminalEvidence("closed", AT + timedelta(hours=25), AT + timedelta(hours=25)),
            (follow(created_at=AT + timedelta(hours=24)),),
            AT + timedelta(hours=26),
            (1, 1, "terminal_after_24h"),
        ),
        (
            "exact 24h refund boundary",
            TerminalEvidence("refunded", AT + timedelta(hours=24), AT + timedelta(hours=24)),
            (follow(created_at=AT + timedelta(hours=24)),),
            AT + timedelta(hours=25),
            (0, 0, "terminal_within_24h_unfollowed"),
        ),
    ],
)
def test_follow_up_truth_table(name, terminal, follows, cutoff, expected) -> None:
    metric = evaluate_clue_followup_round(
        round_value(), follow_ups=follows, terminal=terminal, observed_through=cutoff
    )
    assert (metric.numerator, metric.denominator, metric.reason_code) == expected, name


def test_follow_up_uses_assigned_at_and_normalizes_timezones() -> None:
    round_row = round_value(assigned_at=datetime(2026, 10, 1, 8))
    item = follow(created_at=datetime(2026, 10, 1, 17, tzinfo=timezone(timedelta(hours=8))))
    metric = evaluate_clue_followup_round(
        round_row, follow_ups=(item,), observed_through=datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    )
    assert (metric.numerator, metric.denominator) == (1, 1)


def test_unknown_terminal_time_excludes_follow_any_until_business_time_is_known() -> None:
    metric = evaluate_clue_followup_round(
        round_value(),
        follow_ups=(follow(created_at=AT + timedelta(hours=10)),),
        terminal=TerminalEvidence("refunded", None, AT + timedelta(hours=2)),
        observed_through=AT + timedelta(hours=12),
    )
    assert (metric.numerator, metric.denominator) == (0, 0)
    assert (metric.follow_any_numerator, metric.follow_any_denominator) == (0, 0)
    assert metric.reason_code == "terminal_time_unknown"
    assert metric.follow_record_ids == metric.follow_any_record_ids == ()


def test_unknown_terminal_time_definition_is_explicit() -> None:
    definition = CLUE_FOLLOWUP_METRIC_DEFINITIONS["terminal_time_unknown"]
    assert "0/0" in definition
    assert "待补齐" in definition
    assert "观测时间" in definition
    assert "核销" in CLUE_FOLLOWUP_METRIC_DEFINITIONS["terminal_evidence"]
    assert "全量退款" in CLUE_FOLLOWUP_METRIC_DEFINITIONS["terminal_evidence"]


def test_loader_excludes_canceled_and_late_verification_and_returns_refund_time(db_session) -> None:
    db_session.add_all(
        [
            DimSkuProductRule(sku_id="JC", product_scope="精诚养车"),
            RawDouyinOrder(order_id="O", sku_id="JC", order_status="已支付", sale_time=AT),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            ClueAssignmentRound(
                assignment_round_id="R",
                order_id="O",
                round_no=1,
                assigned_store_id="STORE-A",
                assigned_at=AT,
                execution_mode="formal",
                round_status="active_unfollowed",
            ),
            RawDouyinOrderCoupon(
                coupon_id="C",
                order_id="O",
                raw_order_id=1,
                coupon_status_normalized="refunded",
                coupon_refund_time=AT + timedelta(hours=4),
                latest_refund_at=AT + timedelta(hours=4),
            ),
            RawDouyinVerifyRecord(
                verify_id="CANCELED",
                coupon_id="C",
                verify_status="success",
                verify_time=AT + timedelta(hours=1),
                cancel_time=AT + timedelta(hours=2),
                source_observed_at=AT + timedelta(hours=2),
            ),
            SettlementOrderDetail(
                coupon_id="C",
                order_id="O",
                product_type="保养",
                verify_id="CANCELED",
                is_verified=True,
                verify_time=AT + timedelta(hours=1),
                updated_at=AT + timedelta(hours=2),
            ),
            RawDouyinVerifyRecord(
                verify_id="LATE",
                coupon_id="C",
                verify_status="success",
                verify_time=AT + timedelta(hours=1),
                source_observed_at=CUTOFF + timedelta(hours=1),
            ),
            RawDouyinRefundRecord(
                source_record_key="REFUND",
                order_id="O",
                refund_id="REFUND",
                normalized_refund_status=2,
                raw_refund_status="50",
                refund_completed_at=AT + timedelta(hours=4),
                source_observed_at=AT + timedelta(hours=4),
                payload_hash="refund-hash",
                raw_payload={"refund_type": "2", "refund_completed_at": (AT + timedelta(hours=4)).isoformat()},
            ),
        ]
    )
    db_session.commit()

    evidence = load_clue_followup_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"]
    assert evidence.terminal.kind == "refunded"
    assert evidence.terminal.terminal_at == AT + timedelta(hours=4)
    assert evidence.verifications == ()
    metric = bulk_evaluate_clue_followup_metrics(
        db_session,
        {"O"},
        observed_through=CUTOFF,
    )["R"]
    assert (metric.numerator, metric.denominator) == (0, 0)


def test_partial_or_pending_refund_does_not_create_terminal(db_session) -> None:
    db_session.add_all(
        [
            DimSkuProductRule(sku_id="JC", product_scope="精诚养车"),
            RawDouyinOrder(order_id="O", sku_id="JC", order_status="已支付", sale_time=AT),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            RawDouyinOrderCoupon(
                coupon_id="C",
                order_id="O",
                raw_order_id=1,
                coupon_status_normalized="available",
            ),
            RawDouyinRefundRecord(
                source_record_key="PARTIAL",
                order_id="O",
                refund_id="PARTIAL",
                normalized_refund_status=1,
                raw_refund_status="9",
                refund_applied_at=AT + timedelta(hours=2),
                source_observed_at=AT + timedelta(hours=2),
                payload_hash="partial-hash",
                raw_payload={"refund_type": "1", "refund_applied_at": (AT + timedelta(hours=2)).isoformat()},
            ),
        ]
    )
    db_session.commit()
    assert load_terminal_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"].kind is None


def test_completed_full_refund_record_is_terminal_without_coupon_projection(db_session) -> None:
    db_session.add_all(
        [
            DimSkuProductRule(sku_id="JC", product_scope="精诚养车"),
            RawDouyinOrder(order_id="O", sku_id="JC", order_status="已支付", sale_time=AT),
            RawDouyinRefundRecord(
                source_record_key="FULL-RECORD",
                order_id="O",
                refund_id="FULL-RECORD",
                normalized_refund_status=2,
                raw_refund_status="50",
                refund_completed_at=AT + timedelta(hours=4),
                source_observed_at=AT + timedelta(hours=4),
                payload_hash="full-hash",
                raw_payload={"refund_type": "2"},
            ),
        ]
    )
    db_session.commit()
    terminal = load_terminal_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"]
    assert terminal.kind == "refunded"
    assert terminal.terminal_at == AT + timedelta(hours=4)


def test_order_projection_precedes_stale_raw_clue_status(db_session) -> None:
    db_session.add_all(
        [
            RawDouyinOrder(
                order_id="O",
                order_status="201",
                source_observed_at=AT + timedelta(hours=1),
                updated_at=AT + timedelta(hours=1),
                raw_payload={"order_status": "201"},
            ),
            RawDouyinClue(
                clue_row_key="STALE-CLOSED",
                order_id="O",
                order_status="101",
                source_observed_at=AT + timedelta(hours=1),
                updated_at=AT + timedelta(hours=1),
                raw_payload={"order_status": "101"},
            ),
        ]
    )
    db_session.commit()

    terminal = load_terminal_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"]
    assert terminal.kind is None
    assert load_terminal_evidence(
        db_session, {"O"}, observed_through=CUTOFF, include_raw_clues=False
    )["O"].kind is None


def test_verified_order_projection_is_terminal_without_business_timestamp(db_session) -> None:
    db_session.add(
        RawDouyinOrder(
            order_id="O",
            order_status="1",
            source_observed_at=AT + timedelta(hours=1),
            updated_at=AT + timedelta(hours=1),
            raw_payload={
                "order_status": 1,
                "certificate": [{"item_status": 401, "refund_time": 0}],
            },
        )
    )
    db_session.commit()

    terminal = load_terminal_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"]
    assert terminal.kind == "verified"
    assert terminal.terminal_at is None
    assert terminal.is_terminal is True


def test_closed_order_projection_is_terminal_without_business_timestamp(db_session) -> None:
    db_session.add(
        RawDouyinOrder(
            order_id="O",
            order_status="101",
            source_observed_at=AT + timedelta(hours=1),
            updated_at=AT + timedelta(hours=1),
        )
    )
    db_session.commit()

    terminal = load_terminal_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"]
    assert terminal.kind == "closed"
    assert terminal.terminal_at is None
    assert terminal.observed_at == AT + timedelta(hours=1)


@pytest.mark.parametrize("include_valid_distinct", [False, True])
def test_canceled_verification_suppresses_stale_round_projection(
    db_session, include_valid_distinct: bool
) -> None:
    db_session.add_all(
        [
            RawDouyinOrderCoupon(
                coupon_id="C-CANCELED",
                order_id="O",
                raw_order_id=1,
                coupon_status="unused",
                coupon_status_normalized="available",
                source_observed_at=AT + timedelta(hours=1),
            ),
            ClueAssignmentRound(
                assignment_round_id="R-CANCELED",
                order_id="O",
                round_no=1,
                assigned_store_id="STORE-A",
                assigned_at=AT,
                execution_mode="formal",
                round_status="active_unfollowed",
                verified_at=AT + timedelta(hours=1),
                updated_at=AT + timedelta(hours=2),
            ),
            RawDouyinVerifyRecord(
                verify_id="VERIFY-CANCELED",
                coupon_id="C-CANCELED",
                verify_status="success",
                verify_time=AT + timedelta(hours=1),
                cancel_time=AT + timedelta(hours=2),
                source_observed_at=AT + timedelta(hours=2),
            ),
        ]
    )
    if include_valid_distinct:
        db_session.add_all(
            [
                RawDouyinOrderCoupon(
                    coupon_id="C-VALID",
                    order_id="O",
                    raw_order_id=1,
                    coupon_status="unused",
                    coupon_status_normalized="available",
                    source_observed_at=AT + timedelta(hours=3),
                ),
                RawDouyinVerifyRecord(
                    verify_id="VERIFY-VALID",
                    coupon_id="C-VALID",
                    verify_status="success",
                    verify_time=AT + timedelta(hours=3),
                    source_observed_at=AT + timedelta(hours=3),
                ),
            ]
        )
    db_session.commit()

    full = load_clue_followup_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"]
    terminal_only = load_terminal_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"]
    expected_kind = "verified" if include_valid_distinct else None
    assert full.terminal.kind == expected_kind
    assert terminal_only.kind == expected_kind
    if include_valid_distinct:
        assert full.terminal.evidence_ids == ("VERIFY-VALID",)
        assert {item.verify_id for item in full.verifications} == {"VERIFY-VALID"}
    else:
        assert full.verifications == ()


def test_coupon_only_verified_evidence_is_terminal_without_business_time(db_session) -> None:
    db_session.add(
        RawDouyinOrderCoupon(
            coupon_id="C-401",
            order_id="O",
            raw_order_id=1,
            coupon_status="401",
            source_observed_at=AT + timedelta(hours=2),
        )
    )
    db_session.commit()

    terminal = load_terminal_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"]
    full = load_clue_followup_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"].terminal
    for evidence in (terminal, full):
        assert evidence.kind == "verified"
        assert evidence.terminal_at is None
        assert evidence.observed_at == AT + timedelta(hours=2)
        assert evidence.source == "coupon"


@pytest.mark.parametrize(
    ("settlement_verify_id", "settlement_verify_at", "expected_terminal"),
    [
        ("VERIFY-NEW", AT + timedelta(hours=3), True),
        (None, AT + timedelta(hours=3), True),
        (None, AT + timedelta(hours=1), False),
    ],
)
def test_same_coupon_settlement_verification_matches_cancellation_by_id_then_time(
    db_session,
    settlement_verify_id: str | None,
    settlement_verify_at: datetime,
    expected_terminal: bool,
) -> None:
    db_session.add_all(
        [
            RawDouyinOrderCoupon(
                coupon_id="C-REUSED",
                order_id="O",
                raw_order_id=1,
                coupon_status="unused",
                coupon_status_normalized="available",
                source_observed_at=AT,
            ),
            RawDouyinVerifyRecord(
                verify_id="VERIFY-OLD",
                coupon_id="C-REUSED",
                verify_status="success",
                verify_time=AT + timedelta(hours=1),
                cancel_time=AT + timedelta(hours=2),
                source_observed_at=AT + timedelta(hours=2),
            ),
            SettlementOrderDetail(
                coupon_id="C-REUSED",
                order_id="O",
                product_type="maintenance",
                verify_id=settlement_verify_id,
                is_verified=True,
                verify_time=settlement_verify_at,
                updated_at=settlement_verify_at,
            ),
        ]
    )
    db_session.commit()

    full = load_clue_followup_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"]
    terminal_only = load_terminal_evidence(db_session, {"O"}, observed_through=CUTOFF)["O"]
    assert (full.terminal.kind == "verified") is expected_terminal
    assert (terminal_only.kind == "verified") is expected_terminal
    if expected_terminal:
        expected_id = settlement_verify_id or "C-REUSED"
        assert full.terminal.evidence_ids == (expected_id,)
        assert {item.verify_id for item in full.verifications} == {expected_id}
    else:
        assert full.verifications == ()
