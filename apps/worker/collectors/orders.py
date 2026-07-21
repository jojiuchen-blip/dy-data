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

        order_status_raw = text(first(order, "order_status", "status", "trade_status"))
        sale_channel_raw = text(
            first(order, "sale_channel", "sale_info.channel", "order_sale_info.sale_channel")
        )
        sale_time = source_datetime(first(order, "pay_time", "payment_time"))
        paid_amount = amount_cent(
            first(order, "paid_amount", "pay_amount", "amount.pay_amount")
        )
        coupon_rows = _coupon_rows(order)
        upsert_raw_order(
            session,
            order_id,
            order_status=order_status_raw,
            order_status_raw=order_status_raw,
            order_status_normalized=_normalize_order_status(order_status_raw),
            sku_id=text(first(order, "sku_id", "sku.sku_id", "sku_info.sku_id")),
            product_name=text(first(order, "product_name", "sku_name", "sku.title", "sku_info.title")),
            pay_time=sale_time,
            sale_time=sale_time,
            create_order_time=source_datetime(first(order, "create_order_time", "create_time")),
            paid_amount_cent=paid_amount,
            order_paid_amount_cent=paid_amount or 0,
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
            sale_channel=sale_channel_raw,
            sale_channel_raw=sale_channel_raw,
            sale_channel_normalized=_normalize_sale_channel(sale_channel_raw),
            intention_poi_id=text(first(order, "intention_poi_id", "poi_id")),
            raw_payload=order,
            source_run_id=source_run_id,
        )
        stats.upserted += 1

        for coupon in coupon_rows:
            coupon_id = text(first(coupon, "coupon_id", "certificate_id", "code"))
            if not coupon_id:
                stats.skipped += 1
                continue
            coupon_status_raw = text(
                first(coupon, "coupon_status", "certificate_status", "status", "item_status")
            )
            refunded_amount = amount_cent(
                first(coupon, "coupon_refunded_cent", "refund_amount")
            )
            coupon_paid_amount = amount_cent(
                first(
                    coupon,
                    "coupon_paid_amount_cent",
                    "paid_amount",
                    "pay_amount",
                    "amount.pay_amount",
                )
            )
            if coupon_paid_amount is None and len(coupon_rows) == 1:
                coupon_paid_amount = paid_amount
            latest_refund_at = source_datetime(
                first(coupon, "latest_refund_at", "coupon_refund_time", "refund_time")
            )
            upsert_order_coupon(
                session,
                coupon_id,
                order_id,
                order_item_id=text(first(coupon, "order_item_id", "item_id")),
                coupon_status=coupon_status_raw,
                coupon_status_raw=coupon_status_raw,
                coupon_status_normalized=_normalize_coupon_status(coupon_status_raw),
                coupon_paid_amount_cent=coupon_paid_amount,
                coupon_updated_at=source_datetime(first(coupon, "coupon_updated_at", "update_time", "updated_at", "item_update_time")),
                coupon_refunded_cent=refunded_amount,
                coupon_refunded_amount_cent=refunded_amount or 0,
                coupon_refund_time=latest_refund_at,
                latest_refund_at=latest_refund_at,
                raw_payload=coupon,
                source_run_id=source_run_id,
            )
            stats.upserted += 1
    return stats


def _normalize_order_status(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("-", "_")
    if normalized in {"paid", "success", "completed", "fulfilled"}:
        return "paid"
    if normalized in {"closed", "cancelled", "canceled", "unpaid_closed"}:
        return "closed"
    if normalized in {"refund", "refunded", "fully_refunded"}:
        return "refunded"
    return "unknown"


def _normalize_coupon_status(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("-", "_")
    if normalized in {"available", "unused", "valid"}:
        return "available"
    if normalized in {"verified", "fulfilled", "used", "success"}:
        return "verified"
    if normalized in {"cancelled", "canceled", "revoked", "reversed"}:
        return "cancelled"
    if normalized in {"refund", "refunded", "fully_refunded"}:
        return "refunded"
    return "unknown"


def _normalize_sale_channel(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("-", "_")
    if normalized in {"live", "live_stream", "livestream", "直播"}:
        return "live"
    if normalized in {"short_video", "shortvideo", "video", "短视频"}:
        return "short_video"
    if normalized:
        return "other"
    return "unknown"


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
