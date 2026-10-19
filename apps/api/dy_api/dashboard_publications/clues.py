"""Versioned narrow assignment rounds for clue overview analytics."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Index, Integer,
                        String, Table, Text, and_, case, exists, false, func, insert,
                        literal, or_, select)
from sqlalchemy.orm import Session

from .schema import metadata

SHANGHAI = ZoneInfo("Asia/Shanghai")
VISIBLE_START = datetime(2026, 9, 1, tzinfo=SHANGHAI)
rounds = Table(
    "dashboard_publication_clue_rounds", metadata,
    Column("publication_id", String(64), ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("assignment_round_id", Text, primary_key=True), Column("order_id", Text, nullable=False),
    Column("assigned_at", DateTime(timezone=True)), Column("assigned_store_id", Text),
    Column("assigned_store_name", Text), Column("order_assigned_store_name", Text),
    Column("assigned_province", Text), Column("assigned_city", Text), Column("product_type", Text),
    Column("is_jingcheng", Boolean, nullable=False), Column("is_headquarters", Boolean, nullable=False),
    Column("lead_status", Text), Column("round_status", Text), Column("store_display_status", Text),
    Column("verified_at", DateTime(timezone=True)), Column("is_self_store_verified", Boolean),
    Column("active_clue", Integer, nullable=False), Column("followed_clue", Integer, nullable=False),
    Column("successful_follow_clue", Integer, nullable=False), Column("self_store_verified_clue", Integer, nullable=False),
    Column("pending_reassign_clue", Integer, nullable=False),
    Index("ix_pub_clues_store_date", "publication_id", "assigned_store_id", "assigned_at", "order_id"),
    Index("ix_pub_clues_date_product", "publication_id", "assigned_at", "product_type"),
    Index("ix_pub_clues_order", "publication_id", "order_id"),
)
organizations = Table(
    "dashboard_publication_clue_organizations", metadata,
    Column("publication_id", String(64), ForeignKey("dashboard_publication_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("store_id", Text, primary_key=True), Column("store_name", Text),
    Column("group_name", Text), Column("service_center_name", Text), Column("district_name", Text), Column("area_name", Text),
    Index("ix_pub_clue_org_path", "publication_id", "service_center_name", "district_name", "area_name"),
)
ORG_FIELDS = {"group": ("group_name",), "service_center": ("service_center_name",),
              "district": ("service_center_name", "district_name"),
              "area": ("service_center_name", "district_name", "area_name"), "store": ("store_id",)}


def _bind_time(session, value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if session.get_bind().dialect.name == "sqlite" else value


def build(session: Session, publication_id: str, cutoff: datetime) -> dict[str, Any]:
    """Freeze formal rounds and business interpretation without phones or JSON."""
    from ..models import (ClueAssignmentRound, ClueCenterOrder, ClueMasterLead,
                          DimSkuProductRule, DimStore, DimStoreOrgAssignment, RawDouyinClue, RawDouyinOrder)
    from ..ranking_schema_v1 import org_history
    from .sources import effective_organization_version

    source = ClueAssignmentRound.__table__
    center = ClueCenterOrder.__table__
    lead = ClueMasterLead.__table__
    rule = DimSkuProductRule.__table__
    raw_order = RawDouyinOrder.__table__
    raw_clue = RawDouyinClue.__table__
    membership = exists(select(1).select_from(rule).where(rule.c.product_scope == "精诚养车", or_(
        center.c.product_id == rule.c.sku_id, center.c.product_id == func.nullif(rule.c.product_id, ""),
        exists(select(1).select_from(raw_order).where(raw_order.c.order_id == center.c.order_id, raw_order.c.sku_id == rule.c.sku_id)).correlate(center, rule),
        exists(select(1).select_from(raw_clue).where(raw_clue.c.order_id == center.c.order_id, or_(raw_clue.c.product_id == rule.c.sku_id, raw_clue.c.product_id == func.nullif(rule.c.product_id, "")))).correlate(center, rule),
    ))).correlate(center)
    headquarters = exists(select(1).select_from(lead).where(lead.c.order_id == center.c.order_id,
        lead.c.lifecycle_status == "active", lead.c.pool_location == "headquarters_pool")).correlate(center)
    current = source.c.assignment_round_id == center.c.current_assignment_round_id
    flag = lambda condition: case((condition, 1), else_=0)
    display = case(
        (center.c.lead_status == "converted", "已核销"), (center.c.lead_status == "refunded", "已退款"),
        (source.c.round_status == "expired_pending_reassign", "超期失效"),
        (source.c.follow_result == "request_store_change", "客户要求换门店"),
        (or_(source.c.round_status == "failed_pending_reassign", source.c.follow_result.in_(["lost", "failed"])), "主动战败"),
        (and_(center.c.lead_status == "active", source.c.round_status == "active_followed"), "已跟进"),
        (and_(center.c.lead_status == "active", source.c.round_status == "active_unfollowed"), "待跟进"), else_="不可跟进")
    query = select(literal(publication_id), source.c.assignment_round_id, center.c.order_id,
        source.c.assigned_at, source.c.assigned_store_id, source.c.assigned_store_name, center.c.assigned_store_name,
        center.c.assigned_province, center.c.assigned_city, center.c.product_type, membership, headquarters,
        center.c.lead_status, source.c.round_status, display, source.c.verified_at, source.c.is_self_store_verified,
        flag(and_(current, source.c.round_status.in_(["active_unfollowed", "active_followed"]))),
        flag(source.c.is_followed.is_(True)), flag(source.c.is_follow_success.is_(True)),
        flag(and_(source.c.is_follow_success.is_(True), source.c.is_self_store_verified.is_(True))),
        flag(and_(current, or_(center.c.lead_status == "pending_reassign", source.c.round_status.in_(["failed_pending_reassign", "expired_pending_reassign"]))))
    ).select_from(source.join(center, source.c.order_id == center.c.order_id)).where(
        source.c.execution_mode == "formal", source.c.assigned_at >= _bind_time(session, VISIBLE_START))
    session.execute(insert(rounds).from_select(list(rounds.c.keys()), query))
    organization_mode, organization_version = effective_organization_version(session, cutoff)
    if organization_mode == "history":
        organization_source = select(org_history).where(
            org_history.c.mapping_version == organization_version if organization_version is not None else false()
        ).subquery()
        organization_join = organization_source.c.store_id == DimStore.store_id
    else:
        organization_source = select(DimStoreOrgAssignment).where(DimStoreOrgAssignment.is_active.is_(True)).subquery()
        organization_join = organization_source.c.service_store_code == DimStore.service_store_code
    store = DimStore.__table__
    session.execute(insert(organizations).from_select(list(organizations.c.keys()), select(
        literal(publication_id), store.c.store_id, store.c.store_name,
        *(func.coalesce(organization_source.c[field], "") for field in ("group_name", "service_center_name", "district_name", "area_name"))
    ).select_from(store.outerjoin(organization_source, organization_join)).where(store.c.is_active.is_(True))))
    return {"row_count": session.scalar(select(func.count()).select_from(rounds).where(rounds.c.publication_id == publication_id)), "data_as_of": None}


def _date(value, *, end=False):
    if isinstance(value, datetime):
        return value.astimezone(SHANGHAI) if value.tzinfo else value.replace(tzinfo=SHANGHAI)
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    result = result.astimezone(SHANGHAI) if result.tzinfo else result.replace(tzinfo=SHANGHAI)
    return result + timedelta(days=1) if end and len(str(value)) == 10 else result


def _where(session, publication_id, filters, visible_product_types, current_headquarters_order_ids):
    col = rounds.c
    clauses = [col.publication_id == publication_id]
    for key, column in (("assigned_store_id", col.assigned_store_id), ("lead_status", col.lead_status),
        ("province", col.assigned_province), ("city", col.assigned_city),
        ("round_status", col.round_status), ("store_display_status", col.store_display_status)):
        value = str(filters.get(key) or "").strip()
        if value and value != "all":
            clauses.append(column == value)
    product = str(filters.get("product_type") or "").strip()
    product = {"精诚养车": "jingcheng", "比亚迪本品": "byd", "全部商品": "all"}.get(product, product)
    if product in ("jingcheng", "byd"):
        clauses.append(col.is_jingcheng.is_(product == "jingcheng"))
    elif product and product != "all":
        clauses.append(col.product_type == product)
    if visible_product_types is not None:
        clauses.append(col.product_type.in_(visible_product_types))
    status = filters.get("verification_status")
    if status == "unverified":
        clauses.append(col.verified_at.is_(None))
    elif status in ("self_store_verified", "other_store_verified"):
        clauses.extend([col.verified_at.is_not(None), col.is_self_store_verified.is_(status == "self_store_verified")])
    for key, end, operator in (("assigned_date_start", False, "start"), ("assigned_date_end", True, "end")):
        value = _date(filters.get(key), end=end)
        if value is not None:
            bound = _bind_time(session, value)
            clauses.append(col.assigned_at >= bound if operator == "start" else col.assigned_at < bound)
    query = str(filters.get("q") or "").strip().lower()
    if query:
        clauses.append(or_(func.lower(col.order_id).like(f"%{query}%"), func.lower(col.order_assigned_store_name).like(f"%{query}%")))
    for key in ("organization_store_ids", "scope_store_ids"):
        if filters.get(key) is not None:
            clauses.append(col.assigned_store_id.in_(filters[key]))
    if filters.get("scope_store_ids") is not None:
        clauses.append(col.is_headquarters.is_(False))
        if current_headquarters_order_ids is not None:
            clauses.append(col.order_id.not_in(current_headquarters_order_ids))
    return clauses


def read(session: Session, publication_id: str, filters: dict[str, Any], *,
         visible_product_types: Sequence[str] | None = None,
         current_headquarters_order_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Aggregate frozen rounds with current store/org/product permissions.

    Restricted callers must supply current headquarters order IDs so a pool move
    revokes access immediately, without waiting for the next analytical version.
    """
    if filters.get("scope_store_ids") is not None and current_headquarters_order_ids is None:
        raise ValueError("current_headquarters_order_ids is required for restricted clue access")
    clauses = _where(session, publication_id, filters, visible_product_types, current_headquarters_order_ids)
    names = ["active_clue", "followed_clue", "successful_follow_clue", "self_store_verified_clue", "pending_reassign_clue"]
    orders = select(rounds.c.order_id, *(func.max(rounds.c[name]).label(name) for name in names)).where(*clauses).group_by(rounds.c.order_id).subquery()
    row = session.execute(select(func.count().label("total"), *(func.coalesce(func.sum(orders.c[name]), 0).label(name) for name in names))).mappings().one()
    total = row["total"]
    ratio = lambda value: round(value / total, 4) if total else 0
    return {"total_clues": total, "active_clues": row["active_clue"], "follow_rate": ratio(row["followed_clue"]),
            "follow_success_rate": ratio(row["successful_follow_clue"]), "verified_count": row["self_store_verified_clue"],
            "self_store_verify_rate": ratio(row["self_store_verified_clue"]), "pending_reassign_count": row["pending_reassign_clue"]}


def read_filters(session: Session, publication_id: str, scope_store_ids: Sequence[str] | None = None, *,
                 include_assigned_stores: bool = True, visible_product_types: Sequence[str] | None = None,
                 organization_store_ids: Sequence[str] | None = None,
                 current_headquarters_order_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Return clue filter options from the same publication and current scope."""
    if scope_store_ids is not None and current_headquarters_order_ids is None:
        raise ValueError("current_headquarters_order_ids is required for restricted clue access")
    clauses = _where(session, publication_id, {"scope_store_ids": scope_store_ids,
        "organization_store_ids": organization_store_ids}, visible_product_types, current_headquarters_order_ids)
    def values(column):
        return list(session.scalars(select(column).where(*clauses, column.is_not(None), column != "").distinct().order_by(column)))
    assigned_stores = [dict(row) for row in session.execute(select(rounds.c.assigned_store_id.label("store_id"),
        func.max(func.coalesce(func.nullif(rounds.c.assigned_store_name, ""), rounds.c.assigned_store_id)).label("store_name"))
        .where(*clauses, rounds.c.assigned_store_id.is_not(None), rounds.c.assigned_store_id != "")
        .group_by(rounds.c.assigned_store_id).order_by("store_name", rounds.c.assigned_store_id)).mappings()] if include_assigned_stores else []
    return {"assigned_stores": assigned_stores, "assigned_provinces": values(rounds.c.assigned_province),
        "assigned_cities": values(rounds.c.assigned_city), "product_types": ["精诚养车", "比亚迪本品"],
        "default_product_type": "all", "lead_statuses": values(rounds.c.lead_status),
        "round_statuses": values(rounds.c.round_status),
        "verification_statuses": ["unverified", "self_store_verified", "other_store_verified"]}


def read_store_options(session: Session, publication_id: str, *, q: str | None = None,
                       province: str | None = None, city: str | None = None,
                       selected_store_id: str | None = None, limit: int = 50,
                       scope_store_ids: Sequence[str] | None = None,
                       organization_store_ids: Sequence[str] | None = None,
                       visible_product_types: Sequence[str] | None = None,
                       current_headquarters_order_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Search version-bound store dimensions with current scope enforcement."""
    if scope_store_ids is not None and current_headquarters_order_ids is None:
        raise ValueError("current_headquarters_order_ids is required for restricted clue access")
    base = _where(session, publication_id, {"scope_store_ids": scope_store_ids,
        "organization_store_ids": organization_store_ids}, visible_product_types, current_headquarters_order_ids)
    base.extend([rounds.c.assigned_store_id.is_not(None), rounds.c.assigned_store_id != ""])
    def query(clauses, row_limit):
        return [dict(row) for row in session.execute(select(rounds.c.assigned_store_id.label("store_id"),
            func.max(func.coalesce(func.nullif(rounds.c.assigned_store_name, ""), rounds.c.assigned_store_id)).label("store_name"))
            .where(*clauses).group_by(rounds.c.assigned_store_id).order_by("store_name", rounds.c.assigned_store_id)
            .limit(row_limit)).mappings()]
    bounded_limit = max(1, min(int(limit), 100))
    result = query([*base, rounds.c.assigned_store_id == selected_store_id], 1) if selected_store_id else []
    clauses = list(base)
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        clauses.append(or_(func.lower(rounds.c.assigned_store_name).like(term), func.lower(rounds.c.assigned_store_id).like(term)))
    if province and province.strip():
        clauses.append(rounds.c.assigned_province == province.strip())
    if city and city.strip():
        clauses.append(rounds.c.assigned_city == city.strip())
    seen = {row["store_id"] for row in result}
    for row in query(clauses, bounded_limit):
        if row["store_id"] not in seen:
            result.append(row)
            seen.add(row["store_id"])
        if len(result) >= bounded_limit:
            break
    return {"stores": result}


def read_organization_options(session: Session, publication_id: str, scope_store_ids: Sequence[str] | None = None, *,
                              level: str, q: str = "", selected_key: str = "", limit: int = 50) -> list[dict[str, str]]:
    """Return the frozen organization catalog inside the current account scope."""
    if level not in ORG_FIELDS:
        raise ValueError("请选择有效的组织层级")
    fields = ORG_FIELDS[level]
    columns = [organizations.c[field] for field in fields]
    if level == "store":
        columns.append(organizations.c.store_name)
    query = select(*columns).where(organizations.c.publication_id == publication_id)
    for field in fields:
        query = query.where(organizations.c[field].is_not(None), organizations.c[field] != "")
    if scope_store_ids is not None:
        query = query.where(organizations.c.store_id.in_(scope_store_ids))
    options = {}
    for row in session.execute(query.distinct()).mappings():
        path = [row[field] for field in fields]
        key = json.dumps(path, ensure_ascii=False, separators=(",", ":"))
        label = f"{row['store_name'] or ''} / {row['store_id']}" if level == "store" else " / ".join(path)
        if q.casefold() in label.casefold() or key == selected_key:
            options[key] = {"value": key, "label": label}
    bounded_limit = max(1, min(int(limit), 100))
    result = sorted(options.values(), key=lambda item: item["label"])[:bounded_limit]
    selected = options.get(selected_key)
    if selected and selected not in result:
        result = [selected, *result[:bounded_limit - 1]]
    return result


def organization_scope_store_ids(session: Session, publication_id: str, scope_store_ids: Sequence[str] | None = None, *,
                                 level: str, key: str) -> tuple[str, ...] | None:
    """Resolve a frozen organization selection intersected with live account scope."""
    if level == "all":
        if key:
            raise ValueError("全部层级不能指定组织")
        return tuple(scope_store_ids) if scope_store_ids is not None else None
    if level not in ORG_FIELDS:
        raise ValueError("请选择有效的组织层级")
    if not key:
        return tuple(scope_store_ids) if scope_store_ids is not None else None
    try:
        path = json.loads(key)
    except (TypeError, ValueError) as exc:
        raise ValueError("组织路径格式错误") from exc
    fields = ORG_FIELDS[level]
    if not isinstance(path, list) or len(path) != len(fields) or not all(isinstance(item, str) and item for item in path):
        raise ValueError("请选择完整的组织路径")
    query = select(organizations.c.store_id).where(organizations.c.publication_id == publication_id,
        *(organizations.c[field] == value for field, value in zip(fields, path)))
    if scope_store_ids is not None:
        query = query.where(organizations.c.store_id.in_(scope_store_ids))
    return tuple(session.scalars(query.order_by(organizations.c.store_id)))
