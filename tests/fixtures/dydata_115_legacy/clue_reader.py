# Frozen compatibility evidence from 678429d6; do not update with current readers.
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.orm import Session
from apps.api.dy_api.dashboard_publications.clues import rounds, SHANGHAI, _bind_time
from apps.api.dy_api.dashboard_publications.schema import runs, heads
from apps.api.dy_api.dashboard_publications.lifecycle import PublicationError, Publication, _publication, utc, DEPLOYMENT_PREVIOUS_CONTRACT_PIN_PREFIX
MODULE_CONTRACT_VERSIONS = {'sales': 'product-type-v2', 'clue-overview': 'product-type-v2', 'settlement': 'commission-product-type-v3'}

def resolve_publication(
    session: Session, module: str, publication_id: str | None = None, *,
    allow_previous_deployment: bool = False,
) -> Publication:
    """Resolve once, holding a parent SHARE lock until the caller ends its tx.

    This is permission-neutral. Routes must apply current authorization to
    every projection query, including exports and requests specifying an ID.
    Default HTTP reads may opt in to a compatible snapshot pinned for cutover.
    """
    statement = select(runs).where(runs.c.module == module, runs.c.status == "success")
    if publication_id is not None:
        statement = statement.where(runs.c.id == publication_id)
    else:
        statement = statement.where(runs.c.id == select(heads.c.publication_id)
                                    .where(heads.c.module == module).scalar_subquery())
    postgres = session.get_bind().dialect.name == "postgresql"
    if postgres:
        statement = statement.with_for_update(read=True)
    row = session.execute(statement).mappings().first()
    if row is None:
        if publication_id is not None:
            raise PublicationError("PUBLICATION_EXPIRED", "指定分析版本已过期，请刷新后重试", 410)
        raise PublicationError("PUBLICATION_NOT_READY", "首次分析版本尚未发布", 503)
    expected_contract = MODULE_CONTRACT_VERSIONS.get(module)
    actual_contract = (row["stats_json"] or {}).get("contract_version")
    # Changed analytical classifications need a new complete publication.
    # Original financial rows and independent ranking retain their contracts.
    if expected_contract and actual_contract != expected_contract:
        if publication_id is not None:
            raise PublicationError("PUBLICATION_EXPIRED", "指定分析版本使用旧商品分类，请刷新后重试", 410)
        if (allow_previous_deployment and module == "settlement"
                and isinstance(actual_contract, str) and actual_contract):
            # The deployment pin binds a complete snapshot to the incoming
            # head contract. Only default HTTP reads may use it during cutover.
            previous = select(runs).where(
                runs.c.module == module,
                runs.c.status == "success",
                runs.c.stats_json["contract_version"].as_string() == expected_contract,
                runs.c.pinned_at.is_not(None),
                runs.c.pinned_by.is_not(None),
                runs.c.pin_reason == DEPLOYMENT_PREVIOUS_CONTRACT_PIN_PREFIX + actual_contract,
            ).order_by(runs.c.published_at.desc(), runs.c.id.desc()).limit(1)
            if postgres:
                previous = previous.with_for_update(read=True)
            compatible = session.execute(previous).mappings().first()
            if compatible is not None:
                return replace(_publication(compatible), status="stale")
        raise PublicationError("PUBLICATION_NOT_READY", "新版商品分类分析尚未发布", 503)
    publication = _publication(row)
    # A historical successful version remains readable even after a failed
    # replacement. Status describes freshness, never changes its identity.
    is_active = publication_id is None or session.scalar(
        select(heads.c.publication_id).where(heads.c.module == module)
    ) == publication.id
    if is_active:
        latest = session.execute(select(runs.c.status).where(runs.c.module == module)
                                 .order_by(runs.c.created_at.desc(), runs.c.id.desc()).limit(1)).scalar()
        if latest == "building":
            publication = replace(publication, status="refreshing")
        elif latest == "failed":
            publication = replace(publication, status="failed")
        elif publication.next_refresh_at and datetime.now(UTC) >= publication.next_refresh_at:
            publication = replace(publication, status="stale")
    return publication


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
    if product and product != "all":
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


