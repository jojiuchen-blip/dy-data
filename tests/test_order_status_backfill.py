from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import RawDouyinOrder, RawDouyinOrderCoupon
from apps.worker.order_status_backfill import backfill_normalized_statuses


def test_status_backfill_updates_orders_and_coupons_in_batches(db_session: Session) -> None:
    order_refunded = RawDouyinOrder(
        order_id="order-refunded",
        order_status_raw="1",
        order_status_normalized="unknown",
        raw_payload={"certificate": [{"item_status": 301, "refund_time": 123}]},
    )
    order_active = RawDouyinOrder(
        order_id="order-active",
        order_status_raw="201",
        order_status_normalized="unknown",
        raw_payload={},
    )
    db_session.add_all([order_refunded, order_active])
    db_session.flush()
    db_session.add_all(
        [
            RawDouyinOrderCoupon(
                coupon_id="coupon-verified",
                order_id="order-active",
                raw_order_id=order_active.id,
                coupon_status_raw="401",
                coupon_status_normalized="unknown",
                raw_payload={},
            ),
            RawDouyinOrderCoupon(
                coupon_id="coupon-closed",
                order_id="order-active",
                raw_order_id=order_active.id,
                coupon_status_raw="101",
                coupon_status_normalized="unknown",
                raw_payload={},
            ),
        ]
    )
    db_session.commit()

    result = backfill_normalized_statuses(db_session, batch_size=1)
    db_session.commit()

    assert result == {
        "orders_scanned": 2,
        "orders_updated": 2,
        "coupons_scanned": 2,
        "coupons_updated": 2,
        "dry_run": False,
    }
    assert db_session.get(RawDouyinOrder, order_refunded.id).order_status_normalized == "refunded"
    assert db_session.get(RawDouyinOrder, order_active.id).order_status_normalized == "paid"
    statuses = {
        row.coupon_id: row.coupon_status_normalized
        for row in db_session.scalars(select(RawDouyinOrderCoupon)).all()
    }
    assert statuses == {"coupon-verified": "verified", "coupon-closed": "closed"}

    repeat = backfill_normalized_statuses(db_session, batch_size=1)
    assert repeat["orders_updated"] == 0
    assert repeat["coupons_updated"] == 0


def test_status_backfill_dry_run_does_not_write(db_session: Session) -> None:
    order = RawDouyinOrder(
        order_id="dry-run-order",
        order_status_raw="201",
        order_status_normalized="unknown",
        raw_payload={},
    )
    db_session.add(order)
    db_session.commit()

    result = backfill_normalized_statuses(db_session, dry_run=True)

    assert result["dry_run"] is True
    assert result["orders_scanned"] == 1
    assert result["orders_updated"] == 1
    assert db_session.get(RawDouyinOrder, order.id).order_status_normalized == "unknown"
