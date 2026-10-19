"""Immutable coupon projection and SQL-only sales dashboard reads."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
                        Numeric, String, Table, Text, and_, case, cast, extract,
                        func, insert, literal, literal_column, or_, select, union_all)
from sqlalchemy.orm import Session

from .schema import metadata

SHANGHAI = ZoneInfo("Asia/Shanghai")
coupons = Table(
    "dashboard_publication_sales_coupons", metadata,
    Column("publication_id", String(64), ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("coupon_id", Text, primary_key=True), Column("order_id", Text, nullable=False),
    Column("product_type", Text, nullable=False), Column("sale_store_id", Text),
    Column("sale_time", DateTime(timezone=True)), Column("sale_month", String(7)),
    Column("is_verified", Boolean, nullable=False), Column("verify_store_id", Text),
    Column("verify_time", DateTime(timezone=True)), Column("verify_month", String(7)),
    Column("paid_amount_cent", Integer, nullable=False), Column("cycle_days", Float),
    Column("cycle_sort_days", Numeric(24, 2)),
    Index("ix_pub_sales_sale", "publication_id", "sale_store_id", "sale_month", "product_type"),
    Index("ix_pub_sales_verify", "publication_id", "verify_store_id", "verify_month", "product_type"),
    Index("ix_pub_sales_product", "publication_id", "product_type"),
)
stores = Table(
    "dashboard_publication_sales_stores", metadata,
    Column("publication_id", String(64), ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("store_id", Text, primary_key=True), Column("store_name", Text),
)
product_scopes = Table(
    "dashboard_publication_sales_product_scopes", metadata,
    Column("publication_id", String(64), ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("product_scope", Text, primary_key=True), Column("product_type", Text, primary_key=True),
)


def build(session: Session, publication_id: str, cutoff: datetime) -> dict[str, Any]:
    """Freeze narrow facts with server-side inserts in the caller's transaction."""
    # Models are imported here to avoid coupling metadata registration to the ORM.
    from ..models import DimStore, SettlementOrderDetail, DimSkuProductRule

    source = SettlementOrderDetail.__table__
    pg = session.get_bind().dialect.name == "postgresql"
    def month(column):
        return func.to_char(func.timezone("Asia/Shanghai", column), "YYYY-MM") if pg else func.strftime("%Y-%m", column)
    duration = (extract("epoch", source.c.verify_time - source.c.sale_time) / 86400.0 if pg
                else func.julianday(source.c.verify_time) - func.julianday(source.c.sale_time))
    cycle = case((duration < 0, 0.0), else_=duration)
    query = select(
        literal(publication_id), source.c.coupon_id,
        func.coalesce(func.nullif(source.c.order_id, ""), source.c.coupon_id),
        func.coalesce(source.c.product_type, ""), source.c.sale_store_id,
        source.c.sale_time, month(source.c.sale_time),
        func.coalesce(source.c.is_verified, False), source.c.verify_store_id,
        source.c.verify_time, month(source.c.verify_time),
        func.coalesce(source.c.paid_amount_cent, 0), cycle, func.round(cast(cycle, Numeric(24, 10)), 2),
    ).where(func.coalesce(source.c.is_refund_excluded, False).is_(False))
    session.execute(insert(coupons).from_select(list(coupons.c.keys()), query))
    store = DimStore.__table__
    session.execute(insert(stores).from_select(list(stores.c.keys()), select(literal(publication_id), store.c.store_id, store.c.store_name)))
    rule = DimSkuProductRule.__table__
    session.execute(insert(product_scopes).from_select(list(product_scopes.c.keys()), select(
        literal(publication_id), rule.c.product_scope, rule.c.product_type
    ).where(rule.c.product_scope.is_not(None), rule.c.product_scope != "", rule.c.product_type.is_not(None),
            rule.c.product_type.not_in(["", "all"])).distinct()))
    return {"row_count": session.scalar(select(func.count()).select_from(coupons).where(coupons.c.publication_id == publication_id)), "data_as_of": None}


def _base(publication_id, *, store_id=None, product_type="all", product_scope="all",
          visible_product_types=None, scope_store_ids=None, scope_product_types=None):
    col = coupons.c
    clauses = [col.publication_id == publication_id]
    if store_id:
        clauses.append(or_(col.sale_store_id == store_id, col.verify_store_id == store_id))
    if scope_store_ids is not None:
        clauses.append(or_(col.sale_store_id.in_(scope_store_ids), col.verify_store_id.in_(scope_store_ids)))
    if product_type != "all":
        clauses.append(col.product_type == product_type)
    if visible_product_types is not None:
        clauses.append(col.product_type.in_(visible_product_types))
    if scope_product_types is not None:
        clauses.append(col.product_type.in_(scope_product_types))
    if product_scope != "all":
        clauses.append(col.product_type.in_(select(product_scopes.c.product_type).where(
            product_scopes.c.publication_id == publication_id, product_scopes.c.product_scope == product_scope)))
    return clauses


def _period(column, month, year):
    if month == "history":
        return literal(True)
    if month == "all":
        return and_(column >= f"{year:04d}-01", column <= f"{year:04d}-12")
    datetime.strptime(month, "%Y-%m")
    return column == month


def _conditions(store_id, month, year, scope_store_ids=None):
    col = coupons.c
    sale_store = col.sale_store_id == store_id if store_id else literal(True)
    verify_store = col.verify_store_id == store_id if store_id else literal(True)
    if scope_store_ids is not None:
        sale_store = and_(sale_store, col.sale_store_id.in_(scope_store_ids))
        verify_store = and_(verify_store, col.verify_store_id.in_(scope_store_ids))
    sale = and_(sale_store, _period(col.sale_month, month, year))
    verified = and_(col.is_verified.is_(True), verify_store, _period(col.verify_month, month, year))
    self_verified = and_(sale, col.is_verified.is_(True), col.sale_store_id != "", col.sale_store_id == col.verify_store_id)
    return sale, verified, self_verified


def _metric_groups(session, clauses, sale, verified, self_verified):
    """Reduce coupons to orders before producing global/product aggregates."""
    col = coupons.c
    pg = session.get_bind().dialect.name == "postgresql"
    product_type = col.product_type.collate("C") if pg else col.product_type
    order_id = col.order_id.collate("C") if pg else col.order_id
    grouped_query = select(product_type.label("product_type"), order_id.label("order_id"),
        func.max(case((sale, 1), else_=0)).label("sale"),
        func.max(case((self_verified, 1), else_=0)).label("self_verified"),
        func.max(case((verified, 1), else_=0)).label("verified"),
        func.sum(case((verified, col.paid_amount_cent), else_=0)).label("amount"),
        func.min(case((verified, col.cycle_days))).label("days"),
        func.count().label("source_rows")
    ).where(*clauses, or_(sale, verified))
    grouped = grouped_query.group_by(order_id, product_type).cte("sales_order_products")
    orders = select(grouped.c.order_id, *(func.max(grouped.c[name]).label(name) for name in ("sale", "self_verified", "verified")),
        func.sum(grouped.c.amount).label("amount"), func.min(grouped.c.days).label("days"),
        func.sum(grouped.c.source_rows).label("source_rows")).group_by(grouped.c.order_id).subquery()
    def aggregates(source):
        return [func.coalesce(func.sum(source.c.sale), 0).label("total_sales_order_count"),
                func.coalesce(func.sum(source.c.self_verified), 0).label("self_verify_order_count"),
                func.coalesce(func.sum(source.c.verified), 0).label("total_verify_order_count"),
                func.coalesce(func.sum(source.c.amount), 0).label("actual_verify_amount_cent"),
                func.avg(source.c.days).label("avg_verify_cycle_days"),
                func.coalesce(func.sum(source.c.source_rows), 0).label("source_row_count")]
    query = union_all(select(literal(True).label("is_global"), literal("").label("product_type"), *aggregates(orders)),
        select(literal(False).label("is_global"), grouped.c.product_type, *aggregates(grouped)).group_by(grouped.c.product_type))
    products = []
    metrics = {"total_sales_order_count": 0, "self_verify_order_count": 0, "total_verify_order_count": 0,
               "actual_verify_amount_cent": 0, "self_verify_rate": 0, "avg_verify_cycle_days": None}
    source_row_count = 0
    for value in session.execute(query).mappings():
        row = dict(value)
        is_global = row.pop("is_global")
        source_count = row.pop("source_row_count")
        for field in ("total_sales_order_count", "self_verify_order_count", "total_verify_order_count", "actual_verify_amount_cent"):
            row[field] = int(row[field])
        total, self_count = row["total_sales_order_count"], row["self_verify_order_count"]
        row["self_verify_rate"] = round(self_count / total, 4) if total else 0
        average = row["avg_verify_cycle_days"]
        row["avg_verify_cycle_days"] = round(float(average), 2) if average is not None else None
        if is_global:
            row.pop("product_type")
            metrics, source_row_count = row, int(source_count)
        else:
            products.append(row)
    return metrics, sorted(products, key=lambda row: row["product_type"]), source_row_count


def _cycles(session, clauses, verified):
    col = coupons.c
    product = func.coalesce(func.nullif(col.product_type, literal_column("''")), literal_column("'未映射'"))
    pg = session.get_bind().dialect.name == "postgresql"
    # Binary ordering matches the legacy Python string ordering and avoids
    # expensive locale comparisons while ranking opaque business identifiers.
    if pg:
        product = product.collate("C")
    order_id = col.order_id.collate("C") if pg else col.order_id
    coupon_id = col.coupon_id.collate("C") if pg else col.coupon_id
    choice_order = (col.cycle_sort_days, col.sale_time, coupon_id)
    candidates = select(product.label("product_type"), order_id.label("order_id"), col.cycle_sort_days, col.sale_time, col.verify_time).where(
        *clauses, verified, col.cycle_sort_days.is_not(None))
    if pg:
        # Timestamps are fetched only for the bounded sample set below. Carry
        # just the shortest rounded value through the order/product windows.
        best = select(product.label("product_type"), order_id.label("order_id"),
            func.min(col.cycle_sort_days).label("cycle_sort_days")).where(*clauses, verified,
            col.cycle_sort_days.is_not(None)).group_by(product, order_id).subquery()
    else:
        best_rank = candidates.add_columns(func.row_number().over(
            partition_by=(product, order_id), order_by=choice_order).label("choice")).subquery()
        best = select(best_rank).where(best_rank.c.choice == 1).subquery()
    # The existing contract rounds each point before computing box plot statistics.
    rounded_days = best.c.cycle_sort_days
    time_columns = [] if pg else [best.c.sale_time, best.c.verify_time]
    cycle_window = {"partition_by": best.c.product_type, "order_by": (rounded_days, best.c.order_id), "rows": (None, None)}
    ranked = select(best.c.product_type, best.c.order_id, rounded_days.label("days"), *time_columns,
                    func.row_number().over(**cycle_window).label("position"),
                    func.count().over(**cycle_window).label("count"),
                    func.min(rounded_days).over(**cycle_window).label("min_days"),
                    func.max(rounded_days).over(**cycle_window).label("max_days"),
                    func.avg(rounded_days).over(**cycle_window).label("avg_days")).subquery()
    # Select sample/quantile ranks in SQL after computing each window once.
    # The 90-point grid has odd denominator 89, so nearest rounding cannot
    # encounter the Python/SQL half-to-even versus half-away tie difference.
    last_position = ranked.c.count - 1
    zero_position = ranked.c.position - 1
    # Both operands are integers. Use the SQL integer operator explicitly so
    # SQLAlchemy does not promote this bounded rank arithmetic to Numeric.
    denominator = func.nullif(last_position * 2, 0)
    grid_index = (zero_position * 178 + last_position).op("/", precedence=8, return_type=BigInteger)(denominator)
    on_grid = zero_position == (grid_index * last_position * 2 + 89).op("/", precedence=8, return_type=BigInteger)(178)
    wanted = [ranked.c.count <= 90, on_grid]
    for numerator in (1, 2, 3):
        quantile_position = last_position * numerator
        wanted.extend([zero_position == quantile_position.op("/", precedence=8, return_type=BigInteger)(4),
                       zero_position == (quantile_position + 3).op("/", precedence=8, return_type=BigInteger)(4)])
    selected = select(ranked).where(or_(*wanted)).subquery()
    if pg:
        matches = select(selected, col.sale_time, col.verify_time,
            func.row_number().over(partition_by=(selected.c.product_type, selected.c.position),
                order_by=(col.sale_time, coupon_id)).label("sample_choice")).select_from(selected.join(coupons, and_(
                    *clauses, verified, col.cycle_sort_days == selected.c.days,
                    product == selected.c.product_type, order_id == selected.c.order_id))).subquery()
        query = select(matches).where(matches.c.sample_choice == 1).order_by(matches.c.product_type, matches.c.position)
    else:
        query = select(selected).order_by(selected.c.product_type, selected.c.position)
    grouped_points: dict[str, list[Any]] = {}
    for point in session.execute(query).mappings():
        grouped_points.setdefault(point["product_type"], []).append(point)
    result = []
    for product_type, points in grouped_points.items():
        item = points[0]
        row = {field: item[field] for field in ("count", "min_days", "max_days", "avg_days")}
        row["product_type"] = product_type
        count = row["count"]
        positions = {round(index * (count - 1) / 89) + 1 for index in range(90)} if count > 90 else set(range(1, count + 1))
        quantile_positions = {}
        for key, ratio in (("q1_days", .25), ("median_days", .5), ("q3_days", .75)):
            point = (count - 1) * ratio
            quantile_positions[key] = (math.floor(point) + 1, math.ceil(point) + 1, point % 1)
        by_position = {point["position"]: float(point["days"]) for point in points}
        for key, (low, high, weight) in quantile_positions.items():
            row[key] = round(by_position[low] * (1 - weight) + by_position[high] * weight, 2)
        row["avg_days"] = round(row["avg_days"], 2)
        row["min_days"], row["max_days"] = float(row["min_days"]), float(row["max_days"])
        row["sample_points"] = [{"order_id": point["order_id"], "cycle_days": float(point["days"]), "sale_time": point["sale_time"], "verify_time": point["verify_time"]} for point in points if point["position"] in positions]
        result.append(row)
    return sorted(result, key=lambda row: (-row["count"], row["product_type"]))


def read(session: Session, publication_id: str, *, store_id: str | None = None,
         month: str = "all", year: int | None = None, product_type: str = "all",
         product_scope: str = "all", trend_months: Iterable[str] = (),
         visible_product_types: Sequence[str] | None = None,
         scope_store_ids: Sequence[str] | None = None,
         scope_product_types: Sequence[str] | None = None) -> dict[str, Any]:
    """Read a fixed publication; current authorization is supplied by the caller."""
    year = year or datetime.now(SHANGHAI).year
    store_id = (store_id or "").strip() or None
    product_type = " ".join((product_type or "all").split()) or "all"
    product_scope = " ".join((product_scope or "all").split()) or "all"
    clauses = _base(publication_id, store_id=store_id, product_type=product_type, product_scope=product_scope,
                    visible_product_types=visible_product_types, scope_store_ids=scope_store_ids, scope_product_types=scope_product_types)
    sale, verified, self_verified = _conditions(store_id, month, year, scope_store_ids)
    periods = list(dict.fromkeys(value for value in trend_months if value not in ("all", "history", "")))
    if month not in ("all", "history") and month not in periods:
        periods.insert(0, month)
    if not periods:
        if month == "history":
            periods = list(session.scalars(select(coupons.c.sale_month).where(*clauses, coupons.c.sale_month.is_not(None)).distinct().order_by(coupons.c.sale_month)))
        else:
            periods = [f"{year:04d}-{number:02d}" for number in range(1, 13)]
    sale_store = coupons.c.sale_store_id == store_id if store_id else literal(True)
    verify_store = coupons.c.verify_store_id == store_id if store_id else literal(True)
    if scope_store_ids is not None:
        sale_store = and_(sale_store, coupons.c.sale_store_id.in_(scope_store_ids))
        verify_store = and_(verify_store, coupons.c.verify_store_id.in_(scope_store_ids))
    trend_orders = (select(coupons.c.sale_month, coupons.c.order_id,
        func.max(case((sale_store, 1), else_=0)).label("sale"),
        func.max(case((and_(coupons.c.is_verified.is_(True), verify_store), 1), else_=0)).label("verified"))
        .where(*clauses, coupons.c.sale_month.in_(periods)).group_by(coupons.c.sale_month, coupons.c.order_id).subquery())
    grouped_trend = {row[0]: row[1:] for row in session.execute(select(trend_orders.c.sale_month,
        func.sum(trend_orders.c.sale), func.sum(trend_orders.c.verified)).group_by(trend_orders.c.sale_month))}
    trend = [{"month": period, "order_count": grouped_trend.get(period, (0, 0))[0],
              "verify_order_count": grouped_trend.get(period, (0, 0))[1]} for period in periods]
    store = session.execute(select(stores.c.store_id, stores.c.store_name).where(stores.c.publication_id == publication_id, stores.c.store_id == store_id)).mappings().first() if store_id else None
    metrics, product_rows, source_row_count = _metric_groups(session, clauses, sale, verified, self_verified)
    return {"store": dict(store) if store else {"store_id": store_id or "", "store_name": store_id or "全部门店"},
            "month": month, "product_scope": product_scope, "product_type": product_type,
            "metrics": metrics, "product_rows": product_rows,
            "trend_rows": trend, "cycle_rows": _cycles(session, clauses, verified),
            "source_row_count": source_row_count}


def read_filters(session: Session, publication_id: str, *, visible_product_types: Sequence[str] | None = None,
                 scope_store_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Return version-bound sales dimensions filtered by current access scope."""
    clauses = _base(publication_id, visible_product_types=visible_product_types, scope_store_ids=scope_store_ids)
    sale_months = list(session.scalars(select(coupons.c.sale_month).where(*clauses, coupons.c.sale_month.is_not(None)).distinct().order_by(coupons.c.sale_month.desc())))
    verify_months = list(session.scalars(select(coupons.c.verify_month).where(*clauses, coupons.c.verify_month.is_not(None)).distinct().order_by(coupons.c.verify_month.desc())))
    months = sorted(set(sale_months) | set(verify_months), reverse=True)
    store_query = select(stores.c.store_id, stores.c.store_name).where(stores.c.publication_id == publication_id)
    if scope_store_ids is not None:
        store_query = store_query.where(stores.c.store_id.in_(scope_store_ids))
    types = list(session.scalars(select(coupons.c.product_type).where(*clauses).distinct().order_by(coupons.c.product_type)))
    scope_map: dict[str, list[str]] = {}
    for scope, product in session.execute(select(product_scopes.c.product_scope, product_scopes.c.product_type).where(
            product_scopes.c.publication_id == publication_id, product_scopes.c.product_type.in_(types)).order_by(product_scopes.c.product_scope, product_scopes.c.product_type)):
        scope_map.setdefault(scope, []).append(product)
    return {"years": sorted({int(value[:4]) for value in months}, reverse=True), "months": months,
            "product_types": ["all", *types], "product_scopes": ["all", *scope_map], "product_scope_type_map": scope_map,
            "stores": [dict(row) for row in session.execute(store_query.order_by(stores.c.store_name, stores.c.store_id)).mappings()],
            "sale_months": sale_months, "verify_months": verify_months, "statement_months": [],
            "default_product_type": "all", "period_types": ["MONTHLY", "CUMULATIVE"],
            "fee_directions": ["PROMOTION", "MANAGEMENT"], "formal_period_start_month": "2026-08", "timezone": "Asia/Shanghai"}
