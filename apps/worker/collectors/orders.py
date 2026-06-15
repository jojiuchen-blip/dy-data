from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from apps.worker.collectors.normalizers import amount_cent, first, get_path, source_datetime, text
from apps.worker.collectors.types import CollectionWindow, PhaseStats
from apps.worker.repositories import upsert_order_coupon, upsert_raw_order


def collect_orders(
    session: Session,
    client: Any,
    window: CollectionWindow,
    *,
    source_run_id: str,
) -> PhaseStats:
    stats = PhaseStats(name="orders")
    for order in client.iter_orders(window.start, window.end):
        stats.fetched += 1
        order_id = text(get_path(order, "order_id"))
        if not order_id:
            stats.skipped += 1
            continue

        upsert_raw_order(
            session,
            order_id,
            order_status=text(first(order, "order_status", "status", "trade_status")),
            sku_id=text(first(order, "sku_id", "sku.sku_id", "sku_info.sku_id")),
            product_name=text(first(order, "product_name", "sku_name", "sku.title", "sku_info.title")),
            pay_time=source_datetime(first(order, "pay_time", "payment_time")),
            create_order_time=source_datetime(first(order, "create_order_time", "create_time")),
            paid_amount_cent=amount_cent(first(order, "paid_amount", "pay_amount", "amount.pay_amount")),
            owner_account_id=text(
                first(order, "owner_account_id", "sale_info.transfer_uid", "sale_info.account_id", "order_sale_info.transfer_uid")
            ),
            owner_douyin_uid=text(first(order, "owner_douyin_uid", "sale_info.transfer_douyin_uid", "order_sale_info.transfer_douyin_uid")),
            owner_account_name=text(
                first(
                    order,
                    "owner_account_name",
                    "sale_info.transfer_nickName",
                    "sale_info.transfer_nickname",
                    "order_sale_info.transfer_nickName",
                    "order_sale_info.transfer_nickname",
                )
            ),
            sale_role=text(first(order, "sale_role", "sale_info.role", "order_sale_info.sale_role")),
            sale_channel=text(first(order, "sale_channel", "sale_info.channel", "order_sale_info.sale_channel")),
            intention_poi_id=text(first(order, "intention_poi_id", "poi_id")),
            raw_payload=order,
            source_run_id=source_run_id,
        )
        stats.upserted += 1

        for coupon in _coupon_rows(order):
            coupon_id = text(first(coupon, "coupon_id", "certificate_id", "code"))
            if not coupon_id:
                stats.skipped += 1
                continue
            upsert_order_coupon(
                session,
                coupon_id,
                order_id,
                order_item_id=text(first(coupon, "order_item_id", "item_id")),
                coupon_status=text(first(coupon, "coupon_status", "certificate_status", "status", "item_status")),
                coupon_updated_at=source_datetime(first(coupon, "coupon_updated_at", "update_time", "updated_at", "item_update_time")),
                coupon_refunded_cent=amount_cent(first(coupon, "coupon_refunded_cent", "refund_amount")),
                coupon_refund_time=source_datetime(first(coupon, "coupon_refund_time", "refund_time")),
                raw_payload=coupon,
                source_run_id=source_run_id,
            )
            stats.upserted += 1
    return stats


def _coupon_rows(order: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("certificate", "certificates", "certificate_list", "coupons", "coupon_list"):
        value = order.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    order_items = order.get("order_items") or order.get("items") or []
    rows: list[dict[str, Any]] = []
    if isinstance(order_items, list):
        for item in order_items:
            if not isinstance(item, dict):
                continue
            nested = item.get("certificates") or item.get("coupons")
            if isinstance(nested, list):
                rows.extend({**coupon, "order_item_id": item.get("order_item_id") or item.get("item_id")} for coupon in nested)
    return rows
