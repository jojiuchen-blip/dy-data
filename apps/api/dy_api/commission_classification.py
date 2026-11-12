"""Exact, historical-rule-backed commission classification for the catalog."""

from datetime import datetime, timezone
from collections.abc import Iterable
from typing import Any

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from src.dy_data.product_classification import (
    OFFICIAL_PRODUCT_TYPE, commission_product_type, synced_product_type,
)

from .models import DimSkuProductRule, SkuFeeRule


def reporting_type_expression(sku_column: Any, snapshot_column: Any) -> Any:
    """Resolve display type through exact SKU without updating frozen fields."""
    catalog = DimSkuProductRule.__table__.alias("reporting_type_catalog")
    current_type = select(catalog.c.product_type).where(
        catalog.c.sku_id == sku_column).scalar_subquery()
    return case(
        (or_(snapshot_column == OFFICIAL_PRODUCT_TYPE,
             current_type == OFFICIAL_PRODUCT_TYPE), OFFICIAL_PRODUCT_TYPE),
        (current_type == "精诚养车", "精诚养车"), else_=snapshot_column)


def participation_rules(session: Session, sku_ids: Iterable[str] | None = None,
                        *, as_of: datetime | None = None) -> dict[str, list[SkuFeeRule]]:
    """Return exact published participation evidence, retaining past eligibility.

    A later disabled/zero-rate rule does not erase an earlier positive rule.
    Future effective rules do not establish current or historical participation.
    Product names, product IDs, current on-sale state and internal scope are not
    participation evidence.
    """
    cutoff = as_of or datetime.now(timezone.utc)
    statement = select(SkuFeeRule).where(
        SkuFeeRule.rule_status == 1,
        SkuFeeRule.published_at.is_not(None),
        SkuFeeRule.published_at <= cutoff,
        SkuFeeRule.effective_at <= cutoff,
        or_(SkuFeeRule.promotion_service_fee_rate > 0,
            SkuFeeRule.management_service_fee_rate > 0),
    ).order_by(SkuFeeRule.sku_id, SkuFeeRule.effective_date, SkuFeeRule.rule_version)
    if sku_ids is not None:
        statement = statement.where(SkuFeeRule.sku_id.in_(tuple(set(sku_ids))))
    result: dict[str, list[SkuFeeRule]] = {}
    for rule in session.scalars(statement):
        result.setdefault(rule.sku_id, []).append(rule)
    return result


def maintained_type(row: DimSkuProductRule, requested_type: str,
                    rules: dict[str, list[SkuFeeRule]]) -> str:
    """Maintain approved participant types; preserve unrelated legacy behavior."""
    evidence = rules.get(row.sku_id)
    if not evidence:
        return synced_product_type(row.product_scope, requested_type)
    official = row.product_type == OFFICIAL_PRODUCT_TYPE or any(
        rule.product_type_snapshot == OFFICIAL_PRODUCT_TYPE for rule in evidence)
    return commission_product_type(row.product_type, participates=True, official=official)
