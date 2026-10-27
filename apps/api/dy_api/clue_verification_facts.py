"""Live clue evidence uses the same successful coupon bridge as ranking.

Round scoring flags remain untouched. Reads never backfill business records.
"""
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DimStore, DimStorePoiMapping, RawDouyinOrderCoupon, RawDouyinVerifyRecord,
)

SUCCESS_STATUSES = ("1", "success", "verified", "已核销")


def verification_exists_sql(*, self_store: bool | None = None) -> str:
    """Return a fixed correlated predicate for the authorized outer round r."""
    mapping = ""
    condition = ""
    if self_store is not None:
        mapping = """JOIN (
            SELECT poi_id, MIN(store_id) AS store_id
            FROM dim_store_poi_mappings GROUP BY poi_id
            HAVING COUNT(DISTINCT store_id) = 1
        ) verification_store ON verification_store.poi_id = verification.poi_id"""
        operator = "=" if self_store else "<>"
        condition = f"AND verification_store.store_id {operator} r.assigned_store_id"
    return f"""EXISTS (
        SELECT 1 FROM raw_douyin_order_coupons coupon
        JOIN raw_douyin_verify_records verification ON verification.coupon_id = coupon.coupon_id
        {mapping}
        WHERE coupon.order_id = r.order_id
          AND verification.verify_status IN ('1', 'success', 'verified', '已核销')
          AND verification.verify_time >= r.assigned_at
          AND verification.verify_time <= :clue_verification_cutoff
          AND (verification.cancel_time IS NULL OR verification.cancel_time > :clue_verification_cutoff)
          {condition}
    )"""


def _utc(value: Any) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def enrich_verification_facts(session: Session, rows: list[dict[str, Any]], cutoff: datetime) -> None:
    """Populate authorized list/export/detail rows from bounded raw evidence.

    Prefer a valid same-store coupon, then a uniquely mapped other store. A
    multi-coupon order appears once per selected round, never once per coupon.
    """
    if not rows:
        return
    unique_stores = select(
        DimStorePoiMapping.poi_id,
        func.min(DimStorePoiMapping.store_id).label("store_id"),
    ).group_by(DimStorePoiMapping.poi_id).having(
        func.count(func.distinct(DimStorePoiMapping.store_id)) == 1,
    ).subquery()
    by_order = defaultdict(list)
    order_ids = sorted({row["order_id"] for row in rows})
    for offset in range(0, len(order_ids), 400):
        query = select(
            RawDouyinOrderCoupon.order_id, RawDouyinVerifyRecord.verify_id,
            RawDouyinVerifyRecord.verify_time, unique_stores.c.store_id,
            DimStore.store_name,
        ).join(RawDouyinVerifyRecord,
            RawDouyinVerifyRecord.coupon_id == RawDouyinOrderCoupon.coupon_id,
        ).outerjoin(unique_stores,
            unique_stores.c.poi_id == RawDouyinVerifyRecord.poi_id,
        ).outerjoin(DimStore, DimStore.store_id == unique_stores.c.store_id).where(
            RawDouyinOrderCoupon.order_id.in_(order_ids[offset:offset + 400]),
            RawDouyinVerifyRecord.verify_status.in_(SUCCESS_STATUSES),
            RawDouyinVerifyRecord.verify_time <= cutoff,
            or_(RawDouyinVerifyRecord.cancel_time.is_(None), RawDouyinVerifyRecord.cancel_time > cutoff),
        )
        for fact in session.execute(query).mappings():
            by_order[fact["order_id"]].append(fact)
    for row in rows:
        assigned_at = row.get("assigned_at")
        facts = [fact for fact in by_order[row["order_id"]]
                 if assigned_at and _utc(fact["verify_time"]) >= _utc(assigned_at)]
        facts.sort(key=lambda fact: (
            fact["store_id"] != row.get("assigned_store_id"),
            fact["store_id"] is None, _utc(fact["verify_time"]), fact["verify_id"],
        ))
        fact = facts[0] if facts else None
        row["verified_at"] = fact["verify_time"] if fact else None
        row["verified_store_id"] = fact["store_id"] if fact else None
        row["verified_store_name"] = fact["store_name"] if fact else None
