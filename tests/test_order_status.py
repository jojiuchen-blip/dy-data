from __future__ import annotations

from apps.worker.order_status import (
    normalize_coupon_status,
    normalize_order_status,
    resolve_clue_order_status,
)


def test_numeric_douyin_order_statuses_follow_official_mapping() -> None:
    assert normalize_order_status("201") == "paid"
    assert normalize_order_status("101") == "closed"
    assert normalize_order_status("100") == "unknown"
    assert normalize_order_status("200") == "paid"


def test_completed_order_uses_certificate_evidence_for_refund() -> None:
    refunded = {"order_status": 1, "certificate": [{"item_status": 301, "refund_time": 123}]}
    fulfilled = {"order_status": 1, "certificate": [{"item_status": 401, "refund_time": 0}]}
    transaction_success = {"order_status": 1, "certificate": [{"item_status": 1, "refund_time": 0}]}
    transaction_closed = {"order_status": 1, "certificate": [{"item_status": 101, "refund_time": 0}]}

    assert normalize_order_status("1", refunded) == "refunded"
    assert normalize_order_status("1", transaction_closed) == "closed"
    assert resolve_clue_order_status("1", refunded) == "refunded"
    assert resolve_clue_order_status("1", fulfilled) == "verified"
    assert resolve_clue_order_status("1", transaction_success) == "verified"
    assert resolve_clue_order_status("1", transaction_closed) == "closed"


def test_clue_status_treats_paid_and_waiting_use_as_active() -> None:
    assert resolve_clue_order_status("201") == "active"
    assert resolve_clue_order_status("履约中") == "active"
    assert resolve_clue_order_status("200") == "active"
    assert resolve_clue_order_status("支付成功") == "active"
    assert resolve_clue_order_status("100") == "unknown"
    assert resolve_clue_order_status("101") == "closed"
    assert resolve_clue_order_status("1") == "unknown"
    assert resolve_clue_order_status("交易成功") == "verified"


def test_clue_status_uses_separate_coupon_projection_when_order_payload_is_sparse() -> None:
    assert resolve_clue_order_status(
        "1",
        normalized_order_status="refunded",
        coupon_statuses=["refunded"],
    ) == "refunded"
    assert resolve_clue_order_status(
        "1",
        normalized_order_status="closed",
        coupon_statuses=["closed"],
    ) == "closed"
    assert resolve_clue_order_status(
        "1",
        normalized_order_status="paid",
        coupon_statuses=["verified"],
    ) == "verified"
    assert resolve_clue_order_status(
        "1",
        normalized_order_status="paid",
        coupon_statuses=["available"],
    ) == "unknown"


def test_numeric_coupon_statuses_are_normalized() -> None:
    assert normalize_coupon_status("100") == "available"
    assert normalize_coupon_status("400") == "available"
    assert normalize_coupon_status("401") == "verified"
    assert normalize_coupon_status("1") == "verified"
    assert normalize_coupon_status("101") == "closed"
    assert normalize_coupon_status("301") == "refunded"
