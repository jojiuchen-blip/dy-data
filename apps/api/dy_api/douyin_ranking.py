from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueFollowUpRecord,
    DimAwemeAccount,
    DimStore,
    DimStoreOrgAssignment,
    DimStorePoiMapping,
    DimSkuProductRule,
    RawAwemeBinding,
    RawDouyinClue,
    RawDouyinOrder,
    SettlementOrderDetail,
)


RANKING_LEVELS = {"group", "service_center", "district", "area", "store"}
RANKING_SORT_FIELDS = {"order_count", "order_average", "follow_24h_rate", "verification_rate"}


@dataclass
class _StoreFacts:
    store_id: str
    store_name: str
    service_store_code: str | None
    group_code: str | None
    group_name: str | None
    service_center_name: str | None
    district_name: str | None
    area_name: str | None
    order_count: int = 0
    follow_any_numerator: int = 0
    follow_numerator: int = 0
    follow_denominator: int = 0
    verification_order_ids: set[str] | None = None
    verification_verified_order_ids: set[str] | None = None

    def __post_init__(self) -> None:
        if self.verification_order_ids is None:
            self.verification_order_ids = set()
        if self.verification_verified_order_ids is None:
            self.verification_verified_order_ids = set()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _account_name(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def _store_group_key(facts: _StoreFacts, level: str) -> tuple[str, str]:
    if level == "store":
        return facts.store_id, facts.store_name
    value = (facts.group_name or facts.group_code) if level == "group" else {
        "service_center": facts.service_center_name,
        "district": facts.district_name,
        "area": facts.area_name,
    }[level]
    label = value or "未映射组织"
    return label, label


def _load_store_facts(
    session: Session,
    *,
    scope_store_ids: tuple[str, ...] | None,
    group_name: str | None,
    service_center_name: str | None,
    district_name: str | None,
    area_name: str | None,
    store_id: str | None,
) -> list[_StoreFacts]:
    stmt = (
        select(DimStore, DimStoreOrgAssignment)
        .outerjoin(
            DimStoreOrgAssignment,
            and_(
                DimStoreOrgAssignment.service_store_code == DimStore.service_store_code,
                DimStoreOrgAssignment.is_active.is_(True),
            ),
        )
        .where(DimStore.is_active.is_(True))
    )
    if scope_store_ids is not None:
        if not scope_store_ids:
            return []
        stmt = stmt.where(DimStore.store_id.in_(scope_store_ids))
    if store_id:
        stmt = stmt.where(DimStore.store_id == store_id)
    if service_center_name:
        stmt = stmt.where(DimStoreOrgAssignment.service_center_name == service_center_name)
    if group_name:
        stmt = stmt.where(DimStoreOrgAssignment.group_name == group_name)
    if district_name:
        stmt = stmt.where(DimStoreOrgAssignment.district_name == district_name)
    if area_name:
        stmt = stmt.where(DimStoreOrgAssignment.area_name == area_name)

    facts: list[_StoreFacts] = []
    for store, assignment in session.execute(stmt).all():
        facts.append(
            _StoreFacts(
                store_id=store.store_id,
                store_name=store.store_name,
                service_store_code=store.service_store_code,
                group_code=(assignment.group_code if assignment else None),
                group_name=(assignment.group_name if assignment else None),
                service_center_name=(assignment.service_center_name if assignment else None),
                district_name=(assignment.district_name if assignment else None),
                area_name=(assignment.area_name if assignment else None),
            )
        )
    return facts


def _load_order_counts(
    session: Session,
    facts_by_store: dict[str, _StoreFacts],
    period_start: datetime,
    period_end: datetime,
) -> datetime | None:
    if not facts_by_store:
        return None
    store_ids = tuple(facts_by_store)
    account_rows = session.execute(
        select(DimAwemeAccount.account_id, DimAwemeAccount.nickname, DimAwemeAccount.store_id)
    ).all()
    account_to_store: dict[str, str] = {}
    name_to_stores: defaultdict[str, set[str]] = defaultdict(set)
    for account_id, nickname, mapped_store_id in account_rows:
        if mapped_store_id in facts_by_store:
            account_to_store[str(account_id)] = mapped_store_id
            normalized_name = _account_name(nickname)
            if normalized_name:
                name_to_stores[normalized_name].add(mapped_store_id)
    # Some legacy exports identify the official store account by store_id even
    # before the backend account roster has been imported.
    for store_id in facts_by_store:
        account_to_store.setdefault(store_id, store_id)

    # The official craftsman-binding collector receives the professional
    # account and its Douyin POI, but some historical API payloads do not put
    # the resolved store_id on dim_aweme_accounts. Reuse the existing POI
    # mapping so those accounts still contribute to the store's all-channel
    # order count without a live API call from the dashboard.
    binding_rows = session.execute(
        select(RawAwemeBinding.account_id, RawAwemeBinding.douyin_nickname, DimStorePoiMapping.store_id)
        .join(DimStorePoiMapping, DimStorePoiMapping.poi_id == RawAwemeBinding.poi_id)
        .where(RawAwemeBinding.account_id.is_not(None))
        .where(DimStorePoiMapping.store_id.in_(store_ids))
    ).all()
    for account_id, nickname, mapped_store_id in binding_rows:
        if mapped_store_id not in facts_by_store or not account_id:
            continue
        account_to_store.setdefault(str(account_id), mapped_store_id)
        normalized_name = _account_name(nickname)
        if normalized_name:
            name_to_stores[normalized_name].add(mapped_store_id)

    account_ids = tuple(account_to_store)
    account_names = tuple(name_to_stores)
    if not account_ids and not account_names:
        return None
    owner_filter = []
    if account_ids:
        owner_filter.append(RawDouyinOrder.owner_account_id.in_(account_ids))
    if account_names:
        owner_filter.append(RawDouyinOrder.owner_account_name.in_(account_names))
    time_filter = or_(
        and_(RawDouyinOrder.sale_time >= period_start, RawDouyinOrder.sale_time < period_end),
        and_(
            RawDouyinOrder.sale_time.is_(None),
            RawDouyinOrder.pay_time >= period_start,
            RawDouyinOrder.pay_time < period_end,
        ),
    )
    rows = session.execute(
        select(
            RawDouyinOrder.order_id,
            RawDouyinOrder.owner_account_id,
            RawDouyinOrder.owner_account_name,
            RawDouyinOrder.updated_at,
        )
        .join(
            DimSkuProductRule,
            DimSkuProductRule.sku_id == RawDouyinOrder.sku_id,
        )
        .where(time_filter)
        .where(or_(*owner_filter))
        .where(DimSkuProductRule.product_scope == "精诚养车")
    ).all()
    counted_orders: set[str] = set()
    latest_observed_at: datetime | None = None
    for order_id, owner_account_id, owner_account_name, updated_at in rows:
        order_id = str(order_id)
        if order_id in counted_orders:
            continue
        target_store_id = account_to_store.get(str(owner_account_id)) if owner_account_id else None
        if target_store_id is None:
            candidates = name_to_stores.get(_account_name(owner_account_name), set())
            if len(candidates) == 1:
                target_store_id = next(iter(candidates))
        if target_store_id not in facts_by_store:
            continue
        counted_orders.add(order_id)
        facts_by_store[target_store_id].order_count += 1
        observed = _aware(updated_at)
        if observed is not None and (latest_observed_at is None or observed > latest_observed_at):
            latest_observed_at = observed
    return latest_observed_at


def _load_clue_metrics(
    session: Session,
    facts_by_store: dict[str, _StoreFacts],
    period_start: datetime,
    period_end: datetime,
) -> datetime | None:
    if not facts_by_store:
        return None
    # Keep the eligibility test in SQL instead of expanding every raw order ID
    # into a Python ``IN (...)`` list.  Large local snapshots can contain more
    # than SQLite's bind-variable limit, while the subqueries remain portable
    # to PostgreSQL and preserve the exact product-scope rule.
    eligible_order_ids = select(RawDouyinOrder.order_id).join(
        DimSkuProductRule,
        DimSkuProductRule.sku_id == RawDouyinOrder.sku_id,
    ).where(
        DimSkuProductRule.product_scope == "精诚养车",
        RawDouyinOrder.order_id.is_not(None),
    )
    eligible_clue_order_ids = select(RawDouyinClue.order_id).join(
        DimSkuProductRule,
        DimSkuProductRule.product_id == RawDouyinClue.product_id,
    ).where(
        DimSkuProductRule.product_scope == "精诚养车",
        RawDouyinClue.order_id.is_not(None),
    )
    rounds = list(
        session.scalars(
            select(ClueAssignmentRound)
            .where(ClueAssignmentRound.execution_mode == "formal")
            .where(ClueAssignmentRound.assigned_at >= period_start)
            .where(ClueAssignmentRound.assigned_at < period_end)
            .where(ClueAssignmentRound.assigned_store_id.in_(tuple(facts_by_store)))
            .where(
                or_(
                    ClueAssignmentRound.order_id.in_(eligible_order_ids),
                    ClueAssignmentRound.order_id.in_(eligible_clue_order_ids),
                )
            )
        ).all()
    )
    if not rounds:
        return None
    round_ids = tuple(row.assignment_round_id for row in rounds)
    follow_rows = session.scalars(
        select(ClueFollowUpRecord)
        .where(ClueFollowUpRecord.assignment_round_id.in_(round_ids))
        .where(ClueFollowUpRecord.deleted_at.is_(None))
    ).all()
    follow_by_round: defaultdict[str, list[datetime]] = defaultdict(list)
    follow_any_by_round = defaultdict(list)
    observed_at = datetime.now(timezone.utc)
    for row in follow_rows:
        created_at = _aware(row.created_at)
        if created_at is not None:
            follow_by_round[row.assignment_round_id].append(created_at)
            if created_at <= observed_at:
                follow_any_by_round[row.assignment_round_id].append((created_at, row.assigned_store_id))

    order_ids = {row.order_id for row in rounds}
    all_formal_rounds = list(
        session.scalars(
            select(ClueAssignmentRound)
            .where(ClueAssignmentRound.execution_mode == "formal")
            .where(ClueAssignmentRound.order_id.in_(tuple(order_ids)))
        ).all()
    )
    rounds_by_order: defaultdict[str, list[ClueAssignmentRound]] = defaultdict(list)
    for row in all_formal_rounds:
        rounds_by_order[row.order_id].append(row)

    verify_times_by_order: defaultdict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for row in all_formal_rounds:
        verified_at = _aware(row.verified_at)
        if verified_at is not None and row.verified_store_id:
            verify_times_by_order[row.order_id].append((verified_at, row.verified_store_id))
    settlement_rows = session.execute(
        select(SettlementOrderDetail.order_id, SettlementOrderDetail.verify_time, SettlementOrderDetail.verify_store_id)
        .where(SettlementOrderDetail.order_id.in_(tuple(order_ids)))
        .where(SettlementOrderDetail.is_verified.is_(True))
    ).all()
    for order_id, verify_time, verify_store_id in settlement_rows:
        verified_at = _aware(verify_time)
        if verified_at is not None and verify_store_id:
            verify_times_by_order[order_id].append((verified_at, verify_store_id))

    attributed_stores_by_order: defaultdict[str, set[str]] = defaultdict(set)
    for order_id, verify_times in verify_times_by_order.items():
        candidates = sorted(
            rounds_by_order.get(order_id, []),
            key=lambda row: (_aware(row.assigned_at) or datetime.min.replace(tzinfo=timezone.utc), row.round_no),
        )
        for verify_time, verify_store_id in verify_times:
            effective = [
                row
                for row in candidates
                if (_aware(row.assigned_at) is not None and _aware(row.assigned_at) <= verify_time
                    and row.assigned_store_id == verify_store_id)
            ]
            if effective:
                assigned_store_id = effective[-1].assigned_store_id
                if assigned_store_id in facts_by_store:
                    attributed_stores_by_order[order_id].add(assigned_store_id)

    latest_observed_at: datetime | None = None
    for row in rounds:
        assigned_store_id = row.assigned_store_id
        if assigned_store_id not in facts_by_store:
            continue
        facts = facts_by_store[assigned_store_id]
        facts.follow_denominator += 1
        assigned_at = _aware(row.assigned_at)
        if assigned_at is not None:
            if any(at >= assigned_at and store == assigned_store_id for at, store in follow_any_by_round[row.assignment_round_id]):
                facts.follow_any_numerator += 1
            deadline = assigned_at + timedelta(hours=24)
            if any(assigned_at <= item <= deadline for item in follow_by_round.get(row.assignment_round_id, [])):
                facts.follow_numerator += 1
        facts.verification_order_ids.add(row.order_id)
        if row.order_id in attributed_stores_by_order and assigned_store_id in attributed_stores_by_order[row.order_id]:
            facts.verification_verified_order_ids.add(row.order_id)
        observed = _aware(row.updated_at)
        if observed is not None and (latest_observed_at is None or observed > latest_observed_at):
            latest_observed_at = observed
    return latest_observed_at


def build_douyin_ranking_report(
    session: Session,
    *,
    period_start: datetime,
    period_end: datetime,
    level: str = "service_center",
    scope_store_ids: tuple[str, ...] | None = None,
    group_name: str | None = None,
    service_center_name: str | None = None,
    district_name: str | None = None,
    area_name: str | None = None,
    store_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "order_count",
    sort_order: str = "DESC",
) -> dict[str, Any]:
    normalized_level = level.strip().lower()
    if normalized_level not in RANKING_LEVELS:
        raise ValueError("level must be group, service_center, district, area, or store")
    normalized_sort = sort_by.strip().lower()
    if normalized_sort not in RANKING_SORT_FIELDS:
        raise ValueError("unsupported ranking sort field")
    facts = _load_store_facts(
        session,
        scope_store_ids=scope_store_ids,
        group_name=group_name,
        service_center_name=service_center_name,
        district_name=district_name,
        area_name=area_name,
        store_id=store_id,
    )
    facts_by_store = {row.store_id: row for row in facts}
    observed_values = [
        value
        for value in (
            _load_order_counts(session, facts_by_store, period_start, period_end),
            _load_clue_metrics(session, facts_by_store, period_start, period_end),
        )
        if value is not None
    ]

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in facts:
        key, label = _store_group_key(row, normalized_level)
        item = grouped.setdefault(
            key,
            {
                "key": key,
                "name": label,
                "store_count": 0,
                "order_count": 0,
                "follow_any_numerator": 0,
                "follow_numerator": 0,
                "follow_denominator": 0,
                "verification_numerator": 0,
                "verification_denominator": 0,
                "store_ids": [],
            },
        )
        item["store_count"] += 1
        item["order_count"] += row.order_count
        item["follow_any_numerator"] += row.follow_any_numerator
        item["follow_numerator"] += row.follow_numerator
        item["follow_denominator"] += row.follow_denominator
        item["verification_numerator"] += len(row.verification_verified_order_ids or set())
        item["verification_denominator"] += len(row.verification_order_ids or set())
        item["store_ids"].append(row.store_id)

    rows: list[dict[str, Any]] = []
    for item in grouped.values():
        item["order_average"] = round(item["order_count"] / item["store_count"], 6) if item["store_count"] else None
        item["follow_rate"] = _rate(item["follow_any_numerator"], item["follow_denominator"])
        item["follow_24h_rate"] = _rate(item["follow_numerator"], item["follow_denominator"])
        item["verification_rate"] = _rate(item["verification_numerator"], item["verification_denominator"])
        item.pop("store_ids", None)
        rows.append(item)
    reverse = sort_order.strip().upper() != "ASC"
    rows.sort(key=lambda item: (item.get(normalized_sort) is None, item.get(normalized_sort) or 0, item["name"]), reverse=reverse)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    offset = max(0, page - 1) * page_size
    paged_rows = rows[offset : offset + page_size]
    totals = {
        "store_count": sum(item["store_count"] for item in rows),
        "order_count": sum(item["order_count"] for item in rows),
        "follow_any_numerator": sum(item["follow_any_numerator"] for item in rows),
        "follow_numerator": sum(item["follow_numerator"] for item in rows),
        "follow_denominator": sum(item["follow_denominator"] for item in rows),
        "verification_numerator": sum(item["verification_numerator"] for item in rows),
        "verification_denominator": sum(item["verification_denominator"] for item in rows),
    }
    totals["order_average"] = round(totals["order_count"] / totals["store_count"], 6) if totals["store_count"] else None
    totals["follow_rate"] = _rate(totals["follow_any_numerator"], totals["follow_denominator"])
    totals["follow_24h_rate"] = _rate(totals["follow_numerator"], totals["follow_denominator"])
    totals["verification_rate"] = _rate(totals["verification_numerator"], totals["verification_denominator"])
    return {
        "period_start": period_start,
        "period_end": period_end,
        "level": normalized_level,
        "total": len(rows),
        "page": page,
        "page_size": page_size,
        "rows": paged_rows,
        "totals": totals,
        "latest_observed_at": max(observed_values) if observed_values else None,
        "metric_definitions": {
            "order_count": "统计期内门店账号及所属职人账号卖出的全渠道精诚养车商品订单，按订单ID去重；没有精诚养车商品口径的SKU不计入",
            "order_average": "辖区精诚养车订单量除以辖区全部有效精诚养车门店数",
            "follow_24h_rate": "精诚养车商品对应的正式分配线索中，分配后24小时内存在系统跟进记录的数量除以正式分配数量",
            "verification_rate": "正式分配给本店的精诚养车线索关联订单中，在本店成功核销的订单数除以关联订单总数；上级累加门店分子分母",
        },
    }
