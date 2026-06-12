from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

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
        order_id = _text(_get(order, "order_id"))
        if not order_id:
            stats.skipped += 1
            continue

        upsert_raw_order(
            session,
            order_id,
            order_status=_text(_first(order, "order_status", "status", "trade_status")),
            sku_id=_text(_first(order, "sku_id", "sku.sku_id", "sku_info.sku_id")),
            product_name=_text(_first(order, "product_name", "sku_name", "sku.title", "sku_info.title")),
            pay_time=_datetime(_first(order, "pay_time", "payment_time")),
            create_order_time=_datetime(_first(order, "create_order_time", "create_time")),
            paid_amount_cent=_amount_cent(_first(order, "paid_amount", "pay_amount", "amount.pay_amount")),
            owner_account_id=_text(_first(order, "owner_account_id", "sale_info.transfer_uid", "sale_info.account_id")),
            owner_douyin_uid=_text(_first(order, "owner_douyin_uid", "sale_info.transfer_douyin_uid")),
            owner_account_name=_text(
                _first(order, "owner_account_name", "sale_info.transfer_nickName", "sale_info.transfer_nickname")
            ),
            sale_role=_text(_first(order, "sale_role", "sale_info.role")),
            sale_channel=_text(_first(order, "sale_channel", "sale_info.channel")),
            intention_poi_id=_text(_first(order, "intention_poi_id", "poi_id")),
            raw_payload=order,
            source_run_id=source_run_id,
        )
        stats.upserted += 1

        for coupon in _coupon_rows(order):
            coupon_id = _text(_first(coupon, "coupon_id", "certificate_id", "code"))
            if not coupon_id:
                stats.skipped += 1
                continue
            upsert_order_coupon(
                session,
                coupon_id,
                order_id,
                order_item_id=_text(_first(coupon, "order_item_id", "item_id")),
                coupon_status=_text(_first(coupon, "coupon_status", "certificate_status", "status")),
                coupon_updated_at=_datetime(_first(coupon, "coupon_updated_at", "update_time", "updated_at")),
                coupon_refunded_cent=_amount_cent(_first(coupon, "coupon_refunded_cent", "refund_amount")),
                coupon_refund_time=_datetime(_first(coupon, "coupon_refund_time", "refund_time")),
                raw_payload=coupon,
                source_run_id=source_run_id,
            )
            stats.upserted += 1
    return stats


def _coupon_rows(order: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("certificates", "certificate_list", "coupons", "coupon_list"):
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


def _first(payload: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value = _get(payload, path)
        if value not in (None, ""):
            return value
    return None


def _get(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text or None


def _datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    text = str(value).strip()
    try:
        if text.isdigit():
            return _datetime(int(text))
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _amount_cent(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(Decimal(str(value)))
    except Exception:  # noqa: BLE001 - source field tolerance.
        return None
