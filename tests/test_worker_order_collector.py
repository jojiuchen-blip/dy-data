from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import RawDouyinOrder, RawDouyinOrderCoupon
from apps.worker.collectors.orders import collect_orders
from apps.worker.collectors.types import CollectionWindow


class FakeOrderClient:
    def __init__(self):
        self.calls = 0

    def iter_orders(self, start: datetime, end: datetime):
        self.calls += 1
        yield {
            "order_id": "order-1",
            "order_status": "paid",
            "sku_id": "sku-1",
            "product_name": "Service Product",
            "pay_time": 1767225600,
            "create_order_time": 1767222000,
            "pay_amount": 12345,
            "order_sale_info": {
                "transfer_uid": "owner-1",
                "transfer_douyin_uid": "dy-1",
                "transfer_nickName": "Owner One",
                "sale_role": "sales",
                "sale_channel": "short_video",
            },
            "intention_poi_id": "poi-1",
            "certificate": [
                {
                    "certificate_id": "coupon-1",
                    "order_item_id": "item-1",
                    "item_status": "fulfilled",
                    "item_update_time": 1767230000,
                    "refund_amount": 0,
                }
            ],
        }


def count(session: Session, model: type) -> int:
    value = session.scalar(select(func.count()).select_from(model))
    assert value is not None
    return value


def window() -> CollectionWindow:
    return CollectionWindow(
        start=datetime.fromisoformat("2026-01-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-01-02T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )


def test_collect_orders_upserts_orders_and_coupons_idempotently(db_session: Session):
    client = FakeOrderClient()

    first = collect_orders(db_session, client, window(), source_run_id="run-1")
    first_order = db_session.scalar(
        select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-1")
    )
    first_coupon = db_session.scalar(
        select(RawDouyinOrderCoupon).where(RawDouyinOrderCoupon.coupon_id == "coupon-1")
    )
    assert first_order is not None
    assert first_coupon is not None
    first_order_internal_id = first_order.id
    first_coupon_internal_id = first_coupon.id

    second = collect_orders(db_session, client, window(), source_run_id="run-1")

    assert first.fetched == 1
    assert first.upserted == 2
    assert second.upserted == 2
    assert count(db_session, RawDouyinOrder) == 1
    assert count(db_session, RawDouyinOrderCoupon) == 1

    order = db_session.scalar(
        select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-1")
    )
    assert order is not None
    assert order.sku_id == "sku-1"
    assert order.owner_account_id == "owner-1"
    assert order.owner_douyin_uid == "dy-1"
    assert order.owner_account_name == "Owner One"
    assert order.paid_amount_cent == 12345
    assert order.order_status_raw == "paid"
    assert order.order_status_normalized == "paid"
    assert order.sale_time == order.pay_time
    assert order.order_paid_amount_cent == 12345
    assert order.sale_channel_raw == "short_video"
    assert order.sale_channel_normalized == "short_video"
    assert order.raw_payload["order_sale_info"]["transfer_uid"] == "owner-1"
    assert order.source_run_id == "run-1"
    assert order.id == first_order_internal_id

    coupon = db_session.scalar(
        select(RawDouyinOrderCoupon).where(
            RawDouyinOrderCoupon.coupon_id == "coupon-1"
        )
    )
    assert coupon is not None
    assert coupon.id == first_coupon_internal_id
    assert coupon.order_id == "order-1"
    assert coupon.raw_order_id == order.id
    assert coupon.order_item_id == "item-1"
    assert coupon.coupon_status == "fulfilled"
    assert coupon.coupon_status_raw == "fulfilled"
    assert coupon.coupon_status_normalized == "verified"
    assert coupon.coupon_paid_amount_cent == 12345
    assert coupon.coupon_refunded_amount_cent == 0
    assert coupon.source_run_id == "run-1"


def test_direct_coupon_insert_populates_internal_order_reference(db_session: Session) -> None:
    created_at = datetime.fromisoformat("2026-01-01T00:00:00+08:00")
    order = RawDouyinOrder(
        order_id="legacy-order",
        raw_payload={},
        created_at=created_at,
        updated_at=created_at,
    )
    db_session.add(order)
    db_session.flush()

    coupon = RawDouyinOrderCoupon(
        coupon_id="legacy-coupon",
        order_id="legacy-order",
        raw_payload={},
    )
    db_session.add(coupon)
    db_session.flush()

    assert coupon.raw_order_id == order.id
