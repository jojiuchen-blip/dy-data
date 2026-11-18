"""Frozen first effective verification for each order and actual store."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, String, Table, Text, select
from sqlalchemy.orm import Session

from .schema import metadata

BATCH_SIZE = 500
self_store_verifications = Table(
    "dashboard_publication_self_store_verifications", metadata,
    Column("publication_id", String(64), ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("order_id", Text, primary_key=True), Column("store_id", Text, primary_key=True),
    Column("verify_id", Text, nullable=False), Column("verified_at", DateTime(timezone=True), nullable=False),
    Column("business_date", Date, nullable=False), Column("product_type", Text),
    Column("is_jingcheng", Boolean, nullable=False),
    Column("store_name", Text), Column("province", Text), Column("city", Text),
    Index("ix_pub_self_verify_store_date", "publication_id", "store_id", "business_date"),
    Index("ix_pub_self_verify_date_product", "publication_id", "business_date", "is_jingcheng"),
)


def build(session: Session, publication_id: str, cutoff: datetime) -> int:
    """Freeze all-time first facts before any dashboard's date filtering.

    Coupon orders are the candidate set, so an order needs neither a generated
    clue nor an assigned task. The shared evaluator resolves cancellations and
    deduplicates across every coupon for the order/store before this insert.
    """
    from ..clue_task_metrics import load_self_store_verifications
    from ..models import DimStore, RawDouyinOrderCoupon

    last_order, count = None, 0
    while True:
        query = select(RawDouyinOrderCoupon.order_id).where(
            RawDouyinOrderCoupon.order_id.is_not(None), RawDouyinOrderCoupon.order_id != "",
        ).distinct().order_by(RawDouyinOrderCoupon.order_id).limit(BATCH_SIZE)
        if last_order is not None:
            query = query.where(RawDouyinOrderCoupon.order_id > last_order)
        order_ids = list(session.scalars(query))
        if not order_ids:
            break
        facts = load_self_store_verifications(session, order_ids, observed_through=cutoff)
        stores = {row.store_id: row for row in session.scalars(select(DimStore).where(
            DimStore.store_id.in_({fact.store_id for fact in facts}))) }
        values = []
        for fact in facts:
            store = stores.get(fact.store_id)
            values.append(dict(publication_id=publication_id, order_id=fact.order_id,
                store_id=fact.store_id, verify_id=fact.verify_id, verified_at=fact.verified_at,
                business_date=fact.business_date, product_type=fact.product_type,
                is_jingcheng=fact.is_jingcheng, store_name=store.store_name if store else None,
                province=store.standard_province if store else None, city=store.standard_city if store else None))
        if values:
            session.execute(self_store_verifications.insert(), values)
            count += len(values)
        last_order = order_ids[-1]
    return count
