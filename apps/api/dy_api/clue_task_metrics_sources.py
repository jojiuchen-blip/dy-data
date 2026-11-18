"""Bounded source reads shared by task attribution and self-store volume.

These readers apply observation cutoffs, never reporting periods. In
particular a later coupon cannot become the first verification merely because
the caller selected a later reporting day.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api.dy_api.clue_followup_metrics import VERIFY_SUCCESS_STATUSES
from apps.api.dy_api.models import (
    ClueCenterOrder,
    DimSkuProductRule,
    DimStore,
    DimStorePoiMapping,
    RawDouyinClue,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
)


SOURCE_BATCH_SIZE = 400
INVALID_PRODUCT_TYPES = frozenset({"", "all", "unknown", "keep"})


def utc(value: datetime | None) -> datetime | None:
    """Normalize database timestamps; SQLite naive timestamps represent UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def batches(values: Iterable[str]) -> Iterable[tuple[str, ...]]:
    """Yield deterministic, parameter-bounded identifier groups."""
    ordered = sorted({str(value) for value in values if value is not None and str(value).strip()})
    for offset in range(0, len(ordered), SOURCE_BATCH_SIZE):
        yield tuple(ordered[offset:offset + SOURCE_BATCH_SIZE])


@dataclass(frozen=True)
class OrderProductClassification:
    """Keep actual product type separate from the shared marketing partition."""

    order_id: str
    product_type: str | None
    is_jingcheng: bool

    @property
    def product_scope(self) -> str:
        return "jingcheng" if self.is_jingcheng else "byd"


@dataclass(frozen=True)
class EffectiveVerification:
    """One currently effective successful source verification."""

    order_id: str
    verify_id: str
    verified_at: datetime
    store_id: str | None
    store_name: str | None
    observed_at: datetime | None


def load_order_product_classifications(
    session: Session,
    order_ids: Iterable[str],
) -> dict[str, OrderProductClassification]:
    """Resolve exact types and the ranking's existing three-source membership.

    Exact type follows the current clue queue: order SKU first, then exact
    center SKU, then a unanimous valid product-level classification, finally
    the source center type. Membership independently matches catalog scope
    through raw order SKU, raw clue product or center product. Unknown
    membership belongs to the BYD complement, as in the existing ranking.
    """
    result: dict[str, OrderProductClassification] = {}
    for batch in batches(order_ids):
        order_skus = dict(session.execute(select(
            RawDouyinOrder.order_id, RawDouyinOrder.sku_id,
        ).where(RawDouyinOrder.order_id.in_(batch))).all())
        centers = {row.order_id: row for row in session.execute(select(
            ClueCenterOrder.order_id, ClueCenterOrder.product_id, ClueCenterOrder.product_type,
        ).where(ClueCenterOrder.order_id.in_(batch)))}
        clue_products: defaultdict[str, set[str]] = defaultdict(set)
        for row in session.execute(select(
            RawDouyinClue.order_id, RawDouyinClue.product_id,
        ).where(RawDouyinClue.order_id.in_(batch))):
            if row.product_id:
                clue_products[str(row.order_id)].add(str(row.product_id))
        keys = {str(value) for value in order_skus.values() if value}
        keys.update(str(row.product_id) for row in centers.values() if row.product_id)
        keys.update(value for values in clue_products.values() for value in values)
        rules_by_sku: dict[str, object] = {}
        rules_by_product: defaultdict[str, dict[str, object]] = defaultdict(dict)
        for key_batch in batches(keys):
            for row in session.execute(select(
                DimSkuProductRule.sku_id, DimSkuProductRule.product_id,
                DimSkuProductRule.product_type, DimSkuProductRule.product_scope,
            ).where(or_(DimSkuProductRule.sku_id.in_(key_batch), DimSkuProductRule.product_id.in_(key_batch)))):
                rules_by_sku[str(row.sku_id)] = row
                if row.product_id:
                    rules_by_product[str(row.product_id)][str(row.sku_id)] = row

        def valid_type(row: object | None) -> str | None:
            value = str(getattr(row, "product_type", "") or "").strip()
            return value if value.lower() not in INVALID_PRODUCT_TYPES else None

        def type_for_product(key: str | None) -> str | None:
            if not key:
                return None
            if key in rules_by_sku:
                return valid_type(rules_by_sku[key])
            candidates = tuple(rules_by_product.get(key, {}).values())
            types = {valid_type(row) for row in candidates}
            return next(iter(types)) if len(types) == 1 and None not in types else None

        jingcheng_skus = {key for key, row in rules_by_sku.items() if row.product_scope == "精诚养车"}
        jingcheng_products = {
            str(row.product_id) for row in rules_by_sku.values()
            if row.product_scope == "精诚养车" and row.product_id
        }
        jingcheng_keys = jingcheng_skus | jingcheng_products
        for order_id in batch:
            center = centers.get(order_id)
            center_product = str(center.product_id) if center and center.product_id else None
            sku = order_skus.get(order_id)
            product_type = valid_type(rules_by_sku.get(str(sku))) if sku else type_for_product(center_product)
            if product_type is None and center is not None:
                product_type = center.product_type
            if center is None and not sku:
                candidate_types = {type_for_product(key) for key in clue_products[order_id]}
                if len(candidate_types) == 1 and None not in candidate_types:
                    product_type = next(iter(candidate_types))
            membership = bool(
                sku in jingcheng_skus
                or center_product in jingcheng_keys
                or clue_products[order_id] & jingcheng_keys
            )
            result[order_id] = OrderProductClassification(order_id, product_type, membership)
    return result


def load_effective_verifications(
    session: Session,
    order_ids: Iterable[str],
    *,
    observed_through: datetime,
) -> dict[str, tuple[EffectiveVerification, ...]]:
    """Read the authoritative coupon bridge, including orders with no task.

    Ambiguous POI mappings never pick an arbitrary store. A canceled verify
    identity is omitted without suppressing a distinct subsequent reverify.
    """
    cutoff = utc(observed_through)
    result: dict[str, tuple[EffectiveVerification, ...]] = {}
    for batch in batches(order_ids):
        records = session.execute(select(
            RawDouyinOrderCoupon.order_id,
            RawDouyinVerifyRecord.verify_id, RawDouyinVerifyRecord.verify_time,
            RawDouyinVerifyRecord.verify_status, RawDouyinVerifyRecord.poi_id,
            RawDouyinVerifyRecord.source_observed_at,
        ).join(RawDouyinVerifyRecord,
            RawDouyinVerifyRecord.coupon_id == RawDouyinOrderCoupon.coupon_id,
        ).where(
            RawDouyinOrderCoupon.order_id.in_(batch),
            RawDouyinVerifyRecord.verify_time <= cutoff,
            or_(RawDouyinVerifyRecord.source_observed_at.is_(None), RawDouyinVerifyRecord.source_observed_at <= cutoff),
            or_(RawDouyinVerifyRecord.cancel_time.is_(None), RawDouyinVerifyRecord.cancel_time > cutoff),
        )).all()
        stores_by_poi: defaultdict[str, set[str]] = defaultdict(set)
        for poi_batch in batches(row.poi_id for row in records if row.poi_id):
            for row in session.execute(select(
                DimStorePoiMapping.poi_id, DimStorePoiMapping.store_id,
            ).where(DimStorePoiMapping.poi_id.in_(poi_batch))):
                if row.store_id:
                    stores_by_poi[str(row.poi_id)].add(str(row.store_id))
        resolved_stores = {
            poi_id: next(iter(stores)) for poi_id, stores in stores_by_poi.items() if len(stores) == 1
        }
        store_names: dict[str, str | None] = {}
        for store_batch in batches(resolved_stores.values()):
            store_names.update(session.execute(select(
                DimStore.store_id, DimStore.store_name,
            ).where(DimStore.store_id.in_(store_batch))).all())
        by_order: defaultdict[str, list[EffectiveVerification]] = defaultdict(list)
        for row in records:
            status = str(row.verify_status or "").strip().lower().replace("-", "_")
            if status not in VERIFY_SUCCESS_STATUSES:
                continue
            store_id = resolved_stores.get(str(row.poi_id)) if row.poi_id else None
            by_order[str(row.order_id)].append(EffectiveVerification(
                order_id=str(row.order_id), verify_id=str(row.verify_id),
                verified_at=utc(row.verify_time), store_id=store_id,
                store_name=store_names.get(store_id), observed_at=utc(row.source_observed_at),
            ))
        for order_id in batch:
            result[order_id] = tuple(sorted(by_order[order_id], key=lambda row: (row.verified_at, row.verify_id)))
    return result
