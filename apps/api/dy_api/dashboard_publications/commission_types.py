"""Build reporting type partitions from exact immutable fee/entry identities.

This module never updates settlement facts. Current catalog types are frozen
into the new analysis version; the original financial classification remains
available as snapshot_product_type on displayed lines.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, case, func, literal, or_, select, union
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import CTE, Subquery

from src.dy_data.product_classification import JINGCHENG_PRODUCT_TYPE, OFFICIAL_PRODUCT_TYPE

from ..models import (
    DimSkuProductRule, SettlementFeeAdjustment, SettlementFeeResult, SettlementStatement, SettlementStatementEntry,
)


def _exact_authority(months: Iterable[str]) -> CTE:
    """Reuse complete frozen authority within one statement, never across reads."""
    from apps.worker.protected_billing_authority import protected_entries_relation, protected_statement_condition
    from apps.worker.settlement import _sparse_authority_source

    # Do not filter these relations by requested month: a frozen chain can move
    # to a different month/store, and later adjustments still need its basis.
    statements = select(SettlementStatement.statement_id, SettlementStatement.store_id,
        SettlementStatement.statement_month).where(SettlementStatement.is_current.is_(True),
        protected_statement_condition(SettlementStatement)).cte("classification_protected_statements")
    statements = statements.prefix_with("MATERIALIZED", dialect="postgresql")
    entries = protected_entries_relation(statements=statements).element.cte("classification_protected_entries")
    entries = entries.prefix_with("MATERIALIZED", dialect="postgresql")
    source = _sparse_authority_source(tuple(months), protected_statements=statements, protected_entries=entries)
    # The former four-dimension UNION removed duplicates before selecting exact
    # dimensions. Preserve that set semantics even for malformed duplicate facts.
    return select(source).distinct().cte("classification_exact_authority").prefix_with(
        "MATERIALIZED", dialect="postgresql")


def authority(months: Iterable[str]) -> CTE:
    """Resolve a catalog type only through an exact SKU on an authority row."""
    source = _exact_authority(months)
    result = SettlementFeeResult.__table__.alias("classification_result")
    adjustment = SettlementFeeAdjustment.__table__.alias("classification_adjustment")
    entry = SettlementStatementEntry.__table__.alias("classification_entry")
    catalog = DimSkuProductRule.__table__.alias("classification_catalog")
    joined = source.outerjoin(adjustment, and_(source.c.source_kind == "adjustment",
        adjustment.c.adjustment_id == source.c.source_id)).outerjoin(entry,
        entry.c.statement_entry_id == source.c.frozen_entry_id).outerjoin(result,
        result.c.fee_result_id == func.coalesce(entry.c.original_fee_result_id,
            case((source.c.source_kind == "result", source.c.source_id),
                 else_=adjustment.c.original_fee_result_id)))
    sku_id = func.coalesce(func.nullif(entry.c.sku_id_snapshot, ""), result.c.sku_id)
    joined = joined.outerjoin(catalog, catalog.c.sku_id == sku_id)
    product_type = case(
        (or_(source.c.source_product_type == OFFICIAL_PRODUCT_TYPE,
             catalog.c.product_type == OFFICIAL_PRODUCT_TYPE), OFFICIAL_PRODUCT_TYPE),
        (catalog.c.product_type == JINGCHENG_PRODUCT_TYPE, JINGCHENG_PRODUCT_TYPE),
        else_=case((source.c.source_product_type == "all", "unknown"),
                   else_=source.c.source_product_type))
    reason = case(
        (source.c.store_id.is_(None), "STORE_MISSING"),
        (product_type.in_((OFFICIAL_PRODUCT_TYPE, JINGCHENG_PRODUCT_TYPE)), "CLASSIFIED"),
        (or_(sku_id.is_(None), sku_id == ""), "MISSING_SKU_ID"),
        (catalog.c.sku_id.is_(None), "CATALOG_MISSING"),
        else_="CATALOG_NOT_CANONICAL")
    return select(
        *(source.c[key] for key in ("source_kind", "source_id", "month", "store_id",
            "fee_direction", "order_id", "source_amount_cent", "base_amount_cent",
            "fee_amount_cent", "source_fee_rate", "source_rule_version")),
        entry.c.statement_line_id, sku_id.label("sku_id"),
        source.c.source_product_scope.label("product_scope"),
        source.c.source_product_type.label("snapshot_product_type"),
        product_type.label("product_type"),
        reason.label("classification_reason"),
    ).select_from(joined).cte("classified_authority").prefix_with("MATERIALIZED", dialect="postgresql")


def has_changes(session: Session, months: Iterable[str]) -> bool:
    """Keep legacy versions byte-compatible unless precise SKU types changed."""
    source = authority(months)
    return session.scalar(select(source.c.source_id).where(
        source.c.product_type.in_((JINGCHENG_PRODUCT_TYPE, OFFICIAL_PRODUCT_TYPE)),
        source.c.product_type != source.c.snapshot_product_type).limit(1)) is not None


def coverage(session: Session, months: Iterable[str]) -> list[dict[str, Any]]:
    """Return complete aggregate coverage; unresolved facts stay visible."""
    source = authority(months)
    return [dict(row) for row in session.execute(select(source.c.classification_reason,
        source.c.product_type, func.count().label("fact_count"),
        func.count(func.distinct(source.c.sku_id)).label("sku_count"))
        .group_by(source.c.classification_reason, source.c.product_type)
        .order_by(source.c.classification_reason, source.c.product_type)).mappings()]


def _metrics(source: Subquery) -> dict[str, Any]:
    original = source.c.source_kind == "result"
    promotion = source.c.fee_direction == 1
    management = source.c.fee_direction == 2
    def amount(condition, field):
        return func.coalesce(func.sum(case((condition, source.c[field]), else_=0)), 0)
    values = {
        "sales_order_count": func.count(func.distinct(case((and_(original, promotion), source.c.order_id)))),
        "sales_amount_cent": amount(and_(original, promotion), "source_amount_cent"),
        "verified_order_count": func.count(func.distinct(case((and_(original, management), source.c.order_id)))),
        "verified_amount_cent": amount(and_(original, management), "source_amount_cent"),
    }
    for direction, condition in (("promotion", promotion), ("management", management)):
        values[direction + "_base_cent"] = amount(condition, "base_amount_cent")
        values[direction + "_original_fee_cent"] = amount(and_(original, condition), "fee_amount_cent")
        values[direction + "_adjustment_fee_cent"] = amount(and_(~original, condition), "fee_amount_cent")
        values[direction + "_net_fee_cent"] = amount(condition, "fee_amount_cent")
    values["net_settlement_reference_cent"] = values["promotion_net_fee_cent"] - values["management_net_fee_cent"]
    return values


def partitions(session: Session, months: Iterable[str]) -> list[RowMapping]:
    """Reaggregate type partitions without summing overlapping order counts."""
    source = authority(months)
    fields = [key for key in source.c.keys() if key not in {"product_scope", "product_type"}]
    expanded = union(*(select(*(source.c[key] for key in fields),
        scope.label("product_scope"), product_type.label("product_type"))
        for scope in (source.c.product_scope, literal("all"))
        for product_type in (source.c.product_type, literal("all")))).subquery("classified_dimensions")
    values = _metrics(expanded)
    return list(session.execute(select(expanded.c.store_id, expanded.c.product_scope,
        expanded.c.product_type, *(value.label(key) for key, value in values.items()))
        .group_by(expanded.c.store_id, expanded.c.product_scope, expanded.c.product_type)).mappings())


def lines(session: Session, month: str, store: Any) -> dict[str, list[dict[str, Any]]]:
    """Split display lines by exact SKU type, preserving original line identity."""
    source = authority((month,))
    original = source.c.source_kind == "result"
    fields = {
        "original_entry_count": func.sum(case((original, 1), else_=0)),
        "adjustment_entry_count": func.sum(case((~original, 1), else_=0)),
    }
    for prefix, condition in (("original", original), ("adjustment", ~original)):
        for suffix, column in (("base_cent", "base_amount_cent"), ("fee_cent", "fee_amount_cent")):
            fields[prefix + "_" + suffix] = func.coalesce(func.sum(case((condition, source.c[column]), else_=0)), 0)
    fields["net_base_cent"] = func.coalesce(func.sum(source.c.base_amount_cent), 0)
    fields["net_fee_cent"] = func.coalesce(func.sum(source.c.fee_amount_cent), 0)
    keys = ("store_id", "statement_line_id", "fee_direction", "product_scope", "product_type", "snapshot_product_type")
    groups = list(session.execute(select(*(source.c[key] for key in keys),
        *(value.label(key) for key, value in fields.items())).group_by(*(source.c[key] for key in keys))).mappings())
    rates = {}
    for row in session.execute(select(*(source.c[key] for key in keys), source.c.source_fee_rate,
        source.c.source_rule_version).distinct()).mappings():
        known_rates, versions = rates.setdefault(tuple(row[key] for key in keys), (set(), set()))
        if row["source_fee_rate"] is not None:
            known_rates.add(store._format_rate(row["source_fee_rate"]))
        if row["source_rule_version"]:
            versions.add(str(row["source_rule_version"]))
    result = {}
    for raw in groups:
        row = dict(raw)
        if not row["store_id"]:
            continue
        fee_rates, versions = rates[tuple(row[key] for key in keys)]
        row.update(min_fee_rate=min(fee_rates) if fee_rates else None,
            max_fee_rate=max(fee_rates) if fee_rates else None,
            rule_version_count=len(versions), fee_rates=sorted(fee_rates), rule_versions=sorted(versions))
        row["fee_direction"] = "PROMOTION" if row["fee_direction"] == 1 else "MANAGEMENT"
        result.setdefault(row.pop("store_id"), []).append(row)
    for rows in result.values():
        rows.sort(key=lambda row: (row["fee_direction"], row["product_scope"], row["product_type"], row["snapshot_product_type"]))
    return result
