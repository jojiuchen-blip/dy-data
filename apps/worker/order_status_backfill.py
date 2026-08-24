from __future__ import annotations

import argparse
from typing import Any

from sqlalchemy import bindparam, select, update
from sqlalchemy.orm import Session

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.api.dy_api.models import RawDouyinOrder, RawDouyinOrderCoupon
from apps.worker.order_status import normalize_coupon_status, normalize_order_status

DEFAULT_BATCH_SIZE = 500


def backfill_normalized_statuses(
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> dict[str, int | bool]:
    """Recompute stored status projections without touching raw payloads.

    The cursor is the internal primary key, so the job is bounded in memory and
    safe to repeat. The caller owns the transaction and decides when to commit.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    stats: dict[str, int | bool] = {
        "orders_scanned": 0,
        "orders_updated": 0,
        "coupons_scanned": 0,
        "coupons_updated": 0,
        "dry_run": dry_run,
    }
    last_order_id = 0
    while True:
        rows = session.execute(
            select(
                RawDouyinOrder.id,
                RawDouyinOrder.order_status,
                RawDouyinOrder.order_status_raw,
                RawDouyinOrder.order_status_normalized,
                RawDouyinOrder.raw_payload,
            )
            .where(RawDouyinOrder.id > last_order_id)
            .order_by(RawDouyinOrder.id)
            .limit(batch_size)
        ).all()
        if not rows:
            break

        changes: list[dict[str, Any]] = []
        for row in rows:
            stats["orders_scanned"] = int(stats["orders_scanned"]) + 1
            normalized = normalize_order_status(
                row.order_status_raw or row.order_status,
                row.raw_payload if isinstance(row.raw_payload, dict) else None,
            )
            if row.order_status_normalized != normalized:
                changes.append({"_row_id": row.id, "_normalized": normalized})
        if changes and not dry_run:
            session.execute(
                update(RawDouyinOrder.__table__)
                .where(RawDouyinOrder.id == bindparam("_row_id"))
                .values(order_status_normalized=bindparam("_normalized")),
                changes,
            )
            stats["orders_updated"] = int(stats["orders_updated"]) + len(changes)
        last_order_id = int(rows[-1].id)

    last_coupon_id = 0
    while True:
        rows = session.execute(
            select(
                RawDouyinOrderCoupon.id,
                RawDouyinOrderCoupon.coupon_status,
                RawDouyinOrderCoupon.coupon_status_raw,
                RawDouyinOrderCoupon.coupon_status_normalized,
            )
            .where(RawDouyinOrderCoupon.id > last_coupon_id)
            .order_by(RawDouyinOrderCoupon.id)
            .limit(batch_size)
        ).all()
        if not rows:
            break

        changes = []
        for row in rows:
            stats["coupons_scanned"] = int(stats["coupons_scanned"]) + 1
            normalized = normalize_coupon_status(
                row.coupon_status_raw or row.coupon_status
            )
            if row.coupon_status_normalized != normalized:
                changes.append({"_row_id": row.id, "_normalized": normalized})
        if changes and not dry_run:
            session.execute(
                update(RawDouyinOrderCoupon.__table__)
                .where(RawDouyinOrderCoupon.id == bindparam("_row_id"))
                .values(coupon_status_normalized=bindparam("_normalized")),
                changes,
            )
            stats["coupons_updated"] = int(stats["coupons_updated"]) + len(changes)
        last_coupon_id = int(rows[-1].id)

    return stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Douyin order/coupon status projections without changing raw payloads."
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the normalized status updates. Without this flag the command is a dry run.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before running status backfill.")
    with session_scope(factory) as session:
        stats = backfill_normalized_statuses(
            session,
            batch_size=args.batch_size,
            dry_run=not args.apply,
        )
    print(
        "[worker-status-backfill] "
        f"dry_run={stats['dry_run']} "
        f"orders_scanned={stats['orders_scanned']} "
        f"orders_updated={stats['orders_updated']} "
        f"coupons_scanned={stats['coupons_scanned']} "
        f"coupons_updated={stats['coupons_updated']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
