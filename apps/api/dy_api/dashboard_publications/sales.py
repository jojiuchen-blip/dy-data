"""Immutable coupon projection and SQL-only sales dashboard reads."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
                        Numeric, String, Table, Text, and_, case, cast, distinct, extract,
                        func, insert, literal, or_, select)
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
        func.coalesce(source.c.paid_amount_cent, 0), cycle,
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


def _metrics(session, clauses, sale, verified, self_verified, *, by_product=False):
    col = coupons.c
    fields = [func.count(distinct(case((sale, col.order_id)))).label("total_sales_order_count"),
              func.count(distinct(case((self_verified, col.order_id)))).label("self_verify_order_count"),
              func.count(distinct(case((verified, col.order_id)))).label("total_verify_order_count"),
              func.coalesce(func.sum(case((verified, col.paid_amount_cent), else_=0)), 0).label("actual_verify_amount_cent")]
    if by_product:
        fields.insert(0, col.product_type)
    query = select(*fields).where(*clauses)
    best = select(col.order_id, func.min(col.cycle_days).label("days")).where(*clauses, verified, col.cycle_days.is_not(None))
    if by_product:
        query = query.where(or_(sale, verified)).group_by(col.product_type)
        best = best.add_columns(col.product_type).group_by(col.product_type, col.order_id).subquery()
        averages = dict(session.execute(select(best.c.product_type, func.avg(best.c.days)).group_by(best.c.product_type)).all())
    else:
        best = best.group_by(col.order_id).subquery()
        averages = {None: session.scalar(select(func.avg(best.c.days)))}
    result = []
    for value in session.execute(query).mappings():
        row = dict(value)
        total, self_count = row["total_sales_order_count"], row["self_verify_order_count"]
        row["self_verify_rate"] = round(self_count / total, 4) if total else 0
        average = averages.get(row.get("product_type"))
        row["avg_verify_cycle_days"] = round(average, 2) if average is not None else None
        result.append(row)
    return result


def _cycles(session, clauses, verified):
    col = coupons.c
    product = func.coalesce(func.nullif(col.product_type, ""), "未映射")
    best_rank = select(product.label("product_type"), col.order_id, col.cycle_days, col.sale_time, col.verify_time,
                       func.row_number().over(partition_by=(product, col.order_id), order_by=(func.round(cast(col.cycle_days, Numeric(24, 10)), 2), col.sale_time, col.coupon_id)).label("choice")
                       ).where(*clauses, verified, col.cycle_days.is_not(None)).subquery()
    best = select(best_rank).where(best_rank.c.choice == 1).subquery()
    # The existing contract rounds each point before computing box plot statistics.
    rounded_days = func.round(cast(best.c.cycle_days, Numeric(24, 10)), 2)
    ranked = select(best.c.product_type, best.c.order_id, rounded_days.label("days"),
                    best.c.sale_time, best.c.verify_time,
                    func.row_number().over(partition_by=best.c.product_type, order_by=(rounded_days, best.c.order_id)).label("position")).subquery()
    summary = session.execute(select(ranked.c.product_type, func.count().label("count"), func.min(ranked.c.days).label("min_days"),
                                     func.max(ranked.c.days).label("max_days"), func.avg(ranked.c.days).label("avg_days"))
                              .group_by(ranked.c.product_type).order_by(func.count().desc(), ranked.c.product_type)).mappings()
    result = []
    for item in summary:
        row = dict(item)
        count = row["count"]
        positions = {round(index * (count - 1) / 89) + 1 for index in range(90)} if count > 90 else set(range(1, count + 1))
        quantile_positions = {}
        for key, ratio in (("q1_days", .25), ("median_days", .5), ("q3_days", .75)):
            point = (count - 1) * ratio
            quantile_positions[key] = (math.floor(point) + 1, math.ceil(point) + 1, point % 1)
        needed = positions | {value for low, high, weight in quantile_positions.values() for value in (low, high)}
        points = session.execute(select(ranked).where(ranked.c.product_type == row["product_type"], ranked.c.position.in_(needed)).order_by(ranked.c.position)).mappings().all()
        by_position = {point["position"]: float(point["days"]) for point in points}
        for key, (low, high, weight) in quantile_positions.items():
            row[key] = round(by_position[low] * (1 - weight) + by_position[high] * weight, 2)
        row["avg_days"] = round(row["avg_days"], 2)
        row["min_days"], row["max_days"] = float(row["min_days"]), float(row["max_days"])
        row["sample_points"] = [{"order_id": point["order_id"], "cycle_days": float(point["days"]), "sale_time": point["sale_time"], "verify_time": point["verify_time"]} for point in points if point["position"] in positions]
        result.append(row)
    return result


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
    grouped_trend = {row[0]: row[1:] for row in session.execute(select(coupons.c.sale_month,
        func.count(distinct(case((sale_store, coupons.c.order_id)))),
        func.count(distinct(case((and_(coupons.c.is_verified.is_(True), verify_store), coupons.c.order_id)))))
        .where(*clauses, coupons.c.sale_month.in_(periods)).group_by(coupons.c.sale_month))}
    trend = [{"month": period, "order_count": grouped_trend.get(period, (0, 0))[0],
              "verify_order_count": grouped_trend.get(period, (0, 0))[1]} for period in periods]
    store = session.execute(select(stores.c.store_id, stores.c.store_name).where(stores.c.publication_id == publication_id, stores.c.store_id == store_id)).mappings().first() if store_id else None
    return {"store": dict(store) if store else {"store_id": store_id or "", "store_name": store_id or "全部门店"},
            "month": month, "product_scope": product_scope, "product_type": product_type,
            "metrics": _metrics(session, clauses, sale, verified, self_verified)[0],
            "product_rows": _metrics(session, clauses, sale, verified, self_verified, by_product=True),
            "trend_rows": trend, "cycle_rows": _cycles(session, clauses, verified),
            "source_row_count": session.scalar(select(func.count()).select_from(coupons).where(*clauses, or_(sale, verified)))}


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
