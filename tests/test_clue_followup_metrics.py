from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.api.dy_api.clue_followup_metrics import (
    AssignmentRoundEvidence,
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
