"""Recalculable ranking evidence and immutable dashboard snapshots.

This engine consumes existing raw/round tables. It never fabricates missing
business events or mutates settlement/allocation state. Business publication
uses bounded period queries; historical snapshots remain immutable.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import Session, load_only

from apps.api.dy_api.models import (
    ClueAssignmentRound, ClueCenterOrder, ClueFollowUpRecord, DimAwemeAccount,
    DimStorePoiMapping, DimSkuProductRule, RawAwemeBinding,
    RawDouyinOrder, RawDouyinClue, RawDouyinOrderCoupon, RawDouyinVerifyRecord,
)
from apps.api.dy_api.ranking_schema_v1 import (
    org_history, eligibility, lead_bindings, runs, samples, snapshots,
)
from apps.api.dy_api.ranking_identity import OrderAttributionIndex

METRIC_VERSION = "douyin-ranking-self-store-v5-period-start-sales-org"
MAX_DIMENSION_ROWS = 50000
MAX_ORG_HISTORY_ROWS = 250000
MAX_REPORT_ROWS = 250000
MAX_INLINE_SOURCE_IDENTIFIERS = 16
MAX_SHARED_SOURCE_BYTES = 16 * 1024 * 1024
LEVEL_FIELDS = {
    "group": ("group_key", "group_name"),
    "service_center": ("service_center_key", "service_center_name"),
    "district": ("district_key", "district_name"),
    "area": ("area_key", "area_name"),
    "store": ("store_id", "store_name"),
}
DEFINITIONS = {
    "order_count": "全渠道精诚养车订单，门店及有明确绑定的职人归属，订单ID去重；组织归属固定为统计开始日",
    "order_average": "订单量÷统计开始日适用名单中的精诚养车门店数（含零销量店）",
    "follow_24h_rate": "24小时内有未删除跟进记录的正式轮次数÷正式分配轮次数；上级累加分子分母",
    "verification_rate": "正式分配给本店且成功自店核销的订单数÷正式分配给本店的关联订单数；上级累加门店责任样本",
}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _key(*parts: str) -> str:
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def _lead(round_: ClueAssignmentRound) -> str:
    return round_.lead_key or "order:" + round_.order_id


def _limited_rows(session: Session, statement, limit: int, *, scalar=False, mappings=False):
    result = session.scalars(statement.limit(limit + 1)) if scalar else session.execute(statement.limit(limit + 1))
    rows = list(result.mappings() if mappings else result)
    if len(rows) > limit:
        raise ValueError("指标维度或汇总数据量超过处理上限，请联系管理员分批处理")
    return rows


def calculate_snapshot(
    session: Session, *, run_id: str, period_start: datetime, period_end: datetime,
    observed_through: datetime, roster_at: datetime, eligibility_version: str,
    data_mode: str = "synthetic", max_period_rows: int | None = None,
) -> str:
    """Publish one complete batch atomically; reruns require a new run ID.

    The caller commits the transaction. Reusing an identical run ID is a no-op;
    late-arriving or corrected evidence uses a new ID, retaining old results.
    """
    start, end, cutoff, roster = map(utc, (period_start, period_end, observed_through, roster_at))
    if start >= end or cutoff < start or roster > cutoff:
        raise ValueError("invalid period, observation cutoff or roster date")
    if data_mode not in {"synthetic", "business"}:
        raise ValueError("invalid data mode")

    def bounded(statement, *, scalar=True):
        if max_period_rows is not None:
            statement = statement.limit(max_period_rows + 1)
        result = list(session.scalars(statement) if scalar else session.execute(statement))
        if max_period_rows is not None and len(result) > max_period_rows:
            raise ValueError("所选期间数据量超过单批计算上限，请缩短时间范围")
        return result
    previous = session.execute(select(runs).where(runs.c.run_id == run_id)).mappings().first()
    if previous:
        same = all(utc(previous[k]) == v for k, v in {
            "period_start": start, "period_end": end, "observed_through": cutoff, "roster_at": roster,
        }.items()) and previous["eligibility_version"] == eligibility_version and previous["data_mode"] == data_mode
        if not same or previous["status"] != "success":
            raise ValueError("run ID already used with another configuration")
        return run_id

    history = _limited_rows(session, select(org_history), MAX_ORG_HISTORY_ROWS, mappings=True)
    timeline: dict[str, datetime] = {}
    by_org = {}
    for row in history:
        version, effective = row["mapping_version"], utc(row["effective_from"])
        if version in timeline and timeline[version] != effective:
            raise ValueError("mapping version has inconsistent effective dates")
        timeline[version] = effective
        by_org[(version, row["store_id"])] = row
    if len(set(timeline.values())) != len(timeline):
        raise ValueError("mapping versions have ambiguous effective dates")

    def version_at(at: datetime) -> str | None:
        candidates = [(dt, ver) for ver, dt in timeline.items() if dt <= at]
        return max(candidates)[1] if candidates else None

    roster_version = version_at(roster)
    if not roster_version:
        raise ValueError("no mapping version at roster date")
    eligible_rows = _limited_rows(session, select(eligibility).where(
        eligibility.c.eligibility_version == eligibility_version,
        eligibility.c.product_scope == "精诚养车",
    ), MAX_DIMENSION_ROWS, mappings=True)
    if not eligible_rows or any(utc(row["effective_from"]) > roster for row in eligible_rows):
        raise ValueError("eligibility version missing or not effective at roster date")
    eligible_codes = {row["service_store_code"] for row in eligible_rows}
    roster_rows = [row for row in history if row["mapping_version"] == roster_version]
    eligible_roster = [row for row in roster_rows if row["service_store_code"] in eligible_codes]
    if len({row["service_store_code"] for row in eligible_roster}) != len(eligible_roster):
        raise ValueError("multiple store IDs for one eligible service store in roster")
    if eligible_codes - {row["service_store_code"] for row in roster_rows}:
        raise ValueError("eligible stores are missing organization records")

    pending: list[dict[str, Any]] = []
    quality: defaultdict[str, int] = defaultdict(int)
    source_groups: dict[tuple[str, ...], str] = {}
    shared_source_bytes = 0

    def attribution_evidence(identifiers: tuple[str, ...]) -> dict[str, Any]:
        """Store large immutable source groups once per run, not once per order."""
        nonlocal shared_source_bytes
        if len(identifiers) <= MAX_INLINE_SOURCE_IDENTIFIERS:
            return {"source_identifiers": list(identifiers)}
        group_key = source_groups.get(identifiers)
        if group_key is None:
            payload = json.dumps(identifiers, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            shared_source_bytes += len(payload)
            if shared_source_bytes > MAX_SHARED_SOURCE_BYTES:
                raise ValueError("指标归属证据超过单批上限，请缩短日期范围或核对账号绑定")
            group_key = "sources:" + sha256(payload).hexdigest()
            source_groups[identifiers] = group_key
            pending.append(dict(run_id=run_id, metric_key="order_attribution_sources",
                sample_key=group_key, store_id=None, mapping_version=None, sample_time=None,
                numerator=0, denominator=0, status="excluded", reason_code="shared_source_evidence",
                evidence_json={"source_identifiers": list(identifiers), "source_identifier_count": len(identifiers)}))
        return {"source_identifiers": list(identifiers[:MAX_INLINE_SOURCE_IDENTIFIERS]),
                "source_group_key": group_key, "source_identifier_count": len(identifiers),
                "source_identifiers_truncated": True}

    def add(metric: str, key: str, store: str | None, version: str | None,
            at: datetime | None, numerator: int, denominator: int, evidence: dict,
            reason: str | None = None) -> None:
        if not reason and (version, store) not in by_org:
            reason = "missing_historical_store_mapping"
        if reason:
            quality[reason] += 1
        pending.append(dict(run_id=run_id, metric_key=metric, sample_key=key,
                            store_id=store, mapping_version=version, sample_time=at,
                            numerator=numerator, denominator=denominator,
                            status="unresolved" if reason else "included",
                            reason_code=reason, evidence_json=evidence))

    for row in roster_rows:
        if row["service_store_code"] in eligible_codes:
            add("eligible_store", row["service_store_code"], row["store_id"], roster_version,
                roster, 1, 1, {"eligibility_version": eligibility_version})

    sku_rules = _limited_rows(session, select(DimSkuProductRule).where(
        DimSkuProductRule.product_scope == "精诚养车"), MAX_DIMENSION_ROWS, scalar=True)
    skus = {row.sku_id for row in sku_rules}
    products = {row.product_id for row in sku_rules if row.product_id}
    # Correlate membership to each period candidate. Independent IN subqueries
    # under OR can repeatedly materialize historical product sets on PostgreSQL.
    # Keep LIMIT after membership so unrelated brands do not consume the budget.
    known_orders = select(RawDouyinOrder.order_id).where(
        RawDouyinOrder.order_id == ClueAssignmentRound.order_id,
        RawDouyinOrder.sku_id.in_(skus)).correlate(ClueAssignmentRound).exists()
    known_raw_clues = select(RawDouyinClue.order_id).where(
        RawDouyinClue.order_id == ClueAssignmentRound.order_id,
        RawDouyinClue.product_id.in_(products | skus), RawDouyinClue.order_id.is_not(None)
    ).correlate(ClueAssignmentRound).exists()
    known_center_clues = select(ClueCenterOrder.order_id).where(
        ClueCenterOrder.order_id == ClueAssignmentRound.order_id,
        ClueCenterOrder.product_id.in_(products | skus)).correlate(ClueAssignmentRound).exists()
    selected = bounded(select(ClueAssignmentRound).where(
        ClueAssignmentRound.execution_mode == "formal",
        ClueAssignmentRound.assigned_at >= start, ClueAssignmentRound.assigned_at < end,
        ClueAssignmentRound.assigned_at <= cutoff,
        or_(known_orders, known_raw_clues, known_center_clues),
    ))
    sale_window = or_(
        and_(RawDouyinOrder.sale_time >= start, RawDouyinOrder.sale_time < end,
             RawDouyinOrder.sale_time <= cutoff),
        and_(RawDouyinOrder.sale_time.is_(None), RawDouyinOrder.pay_time >= start,
             RawDouyinOrder.pay_time < end, RawDouyinOrder.pay_time <= cutoff),
    )
    orders = bounded(select(RawDouyinOrder).where(
        RawDouyinOrder.sku_id.in_(skus), sale_window).options(load_only(
            RawDouyinOrder.order_id, RawDouyinOrder.sku_id,
            RawDouyinOrder.sale_time, RawDouyinOrder.pay_time,
            RawDouyinOrder.owner_account_id, RawDouyinOrder.owner_douyin_uid,
            RawDouyinOrder.owner_account_name, RawDouyinOrder.sale_role, RawDouyinOrder.sale_channel)))
    poi_rows = _limited_rows(session, select(DimStorePoiMapping.poi_id, DimStorePoiMapping.store_id), MAX_DIMENSION_ROWS)
    poi_candidates: defaultdict[str, set[str]] = defaultdict(set)
    for poi, store in poi_rows:
        poi_candidates[poi].add(store)
    poi_stores = {poi: next(iter(stores)) for poi, stores in poi_candidates.items() if len(stores) == 1}
    owner_index = OrderAttributionIndex(
        accounts=_limited_rows(session, select(DimAwemeAccount), MAX_DIMENSION_ROWS, scalar=True),
        bindings=_limited_rows(session, select(RawAwemeBinding), MAX_DIMENSION_ROWS, scalar=True),
        poi_to_store=poi_rows)
    for order in orders:
        at = order.sale_time or order.pay_time
        if not at or not start <= utc(at) < end or utc(at) > cutoff:
            continue
        at = utc(at)
        owner = owner_index.resolve(occurred_at=at, owner_account_id=order.owner_account_id,
            owner_douyin_uid=order.owner_douyin_uid, owner_account_name=order.owner_account_name)
        store = owner.store_id
        # Sales and their eligible-store denominator use the same period-start
        # organization. Lead responsibility remains pinned independently below.
        version = roster_version
        reason = None if store else owner.reason
        if owner.historical_period_unverified:
            quality["orders_historical_binding_unverified"] += 1
        add("order_count", order.order_id, store, version, at, 1, 0,
            {"order_id": order.order_id, "owner_account_id": order.owner_account_id,
             "sale_role": order.sale_role, "sale_channel": order.sale_channel,
             "sku_id": order.sku_id, "attribution_reason": owner.reason,
             **attribution_evidence(owner.source_identifiers),
             "historical_period_unverified": owner.historical_period_unverified}, reason)
        if store and (version, store) in by_org and by_org[(version, store)]["service_store_code"] not in eligible_codes:
            quality["orders_outside_eligibility"] += 1

    formal = bounded(select(ClueAssignmentRound).where(
        ClueAssignmentRound.execution_mode == "formal",
        or_(ClueAssignmentRound.lead_key.in_({row.lead_key for row in selected if row.lead_key}),
            ClueAssignmentRound.order_id.in_({row.order_id for row in selected if not row.lead_key})),
        ClueAssignmentRound.assigned_at.is_not(None),
        ClueAssignmentRound.assigned_at <= cutoff,
    ))
    first_by_lead: dict[str, datetime] = {}
    for row in formal:
        key, at = _lead(row), utc(row.assigned_at)
        first_by_lead[key] = min(first_by_lead.get(key, at), at)
    bindings = {row["lead_key"]: row for row in _limited_rows(session, select(lead_bindings).where(
        lead_bindings.c.lead_key.in_(first_by_lead)), MAX_DIMENSION_ROWS, mappings=True)}
    new_bindings = []
    versions = {}
    for key, at in first_by_lead.items():
        pinned = bindings.get(key)
        if pinned:
            versions[key] = pinned["mapping_version"]
            if utc(pinned["first_assigned_at"]) != at:
                quality["first_assignment_changed_requires_review"] += 1
        else:
            versions[key] = version_at(at)
            if versions[key]:
                new_bindings.append(dict(lead_key=key, first_assigned_at=at, mapping_version=versions[key]))

    follow_by_round: defaultdict[str, list[Any]] = defaultdict(list)
    for row in bounded(select(ClueFollowUpRecord).where(
        ClueFollowUpRecord.assignment_round_id.in_([row.assignment_round_id for row in selected]),
        ClueFollowUpRecord.deleted_at.is_(None), ClueFollowUpRecord.created_at <= cutoff,
    )):
        follow_by_round[row.assignment_round_id].append(row)
    responsibilities: defaultdict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in selected:
        at, version = utc(row.assigned_at), versions.get(_lead(row))
        evidence = [item.follow_up_record_id for item in follow_by_round[row.assignment_round_id]
                    if item.assigned_store_id == row.assigned_store_id
                    and at <= utc(item.created_at) <= at + timedelta(hours=24)]
        add("follow_24h", row.assignment_round_id, row.assigned_store_id, version, at,
            int(bool(evidence)), 1, {"order_id": row.order_id, "lead_key": _lead(row),
                                   "round_id": row.assignment_round_id, "follow_record_ids": evidence})
        any_evidence = [item.follow_up_record_id for item in follow_by_round[row.assignment_round_id]
                        if item.assigned_store_id == row.assigned_store_id and utc(item.created_at) >= at]
        add("follow_any", row.assignment_round_id, row.assigned_store_id, version, at,
            int(bool(any_evidence)), 1, {"order_id": row.order_id, "follow_record_ids": any_evidence})
        if at + timedelta(hours=24) > cutoff:
            quality["follow_rounds_under_observation"] += 1
        responsibilities[(row.order_id, row.assigned_store_id)].append(row)

    # Coupons are the authoritative bridge: verification has no order_id column.
    verify_by_order: defaultdict[str, list[Any]] = defaultdict(list)
    verification_rows = bounded(
        select(RawDouyinOrderCoupon.order_id, RawDouyinVerifyRecord)
        .join(RawDouyinVerifyRecord, RawDouyinVerifyRecord.coupon_id == RawDouyinOrderCoupon.coupon_id)
        .where(RawDouyinOrderCoupon.order_id.in_({key[0] for key in responsibilities}))
        , scalar=False)
    for order_id, record in verification_rows:
        verify_by_order[order_id].append(record)
    for (order_id, store), assigned in responsibilities.items():
        earliest = min(assigned, key=lambda row: (utc(row.assigned_at), row.assignment_round_id))
        at, version = utc(earliest.assigned_at), versions.get(_lead(earliest))
        successful = [record for record in verify_by_order[order_id]
                      if record.verify_status in {"1", "success", "verified", "已核销"}
                      and record.verify_time and at <= utc(record.verify_time) <= cutoff
                      and (not record.cancel_time or utc(record.cancel_time) > cutoff)
                      and poi_stores.get(record.poi_id) == store]
        reason = "conflicting_responsibility_versions" if len({versions.get(_lead(row)) for row in assigned}) > 1 else None
        add("self_verification", _key(order_id, store or ""), store, version, at,
            int(bool(successful)), 1,
            {"order_id": order_id, "round_ids": [row.assignment_round_id for row in assigned],
             "self_verify_ids": [row.verify_id for row in successful]}, reason)

    counters: defaultdict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    for item in pending:
        if item["status"] == "included":
            key = (item["store_id"], item["mapping_version"], item["metric_key"])
            counters[key][0] += item["numerator"]
            counters[key][1] += item["denominator"]
    # One savepoint prevents partially published evidence/bindings on failure.
    with session.begin_nested():
        session.execute(runs.insert().values(
            run_id=run_id, period_start=start, period_end=end, observed_through=cutoff,
            roster_at=roster, eligibility_version=eligibility_version, metric_version=METRIC_VERSION,
            data_mode=data_mode, status="building", quality_json=dict(quality), created_at=datetime.now(timezone.utc)))
        if new_bindings:
            session.execute(lead_bindings.insert(), new_bindings)
        if pending:
            session.execute(samples.insert(), pending)
        if counters:
            session.execute(snapshots.insert(), [dict(run_id=run_id, store_id=store,
                mapping_version=version, metric_key=metric, numerator=counts[0], denominator=counts[1])
                for (store, version, metric), counts in counters.items()])
        session.execute(runs.update().where(runs.c.run_id == run_id).values(status="success"))
    return run_id


def read_snapshot_report(
    session: Session, *, period_start: datetime, period_end: datetime, level: str = "group",
    scope_store_ids: tuple[str, ...] | None = None, group_name: str | None = None,
    service_center_name: str | None = None, district_name: str | None = None,
    area_name: str | None = None, store_id: str | None = None,
    page: int = 1, page_size: int = 50, sort_by: str = "order_count", sort_order: str = "DESC",
    run_id: str | None = None, data_mode: str | None = None,
) -> dict[str, Any]:
    """Aggregate only authorized frozen store fragments, then rank and paginate."""
    if level not in LEVEL_FIELDS or sort_by not in {"order_count", "order_average", "follow_24h_rate", "verification_rate"}:
        raise ValueError("invalid level or sort")
    query = select(runs).where(runs.c.status == "success", runs.c.period_start == utc(period_start),
                               runs.c.period_end == utc(period_end))
    if data_mode is not None:
        if data_mode not in {"synthetic", "business"}:
            raise ValueError("invalid data mode")
        query = query.where(runs.c.data_mode == data_mode)
    if run_id:
        query = query.where(runs.c.run_id == run_id)
    run = session.execute(query.order_by(runs.c.created_at.desc(), runs.c.run_id.desc()).limit(1)).mappings().first()
    if not run:
        raise ValueError("该期间尚未生成指标快照，请等待数据处理完成或调整日期范围")
    query = select(snapshots, org_history).join(org_history,
        (snapshots.c.mapping_version == org_history.c.mapping_version) &
        (snapshots.c.store_id == org_history.c.store_id)).where(snapshots.c.run_id == run["run_id"])
    if scope_store_ids is not None:
        query = query.where(snapshots.c.store_id.in_(scope_store_ids))
    for column, value in [(org_history.c.group_name, group_name), (org_history.c.service_center_name, service_center_name),
                          (org_history.c.district_name, district_name), (org_history.c.area_name, area_name),
                          (org_history.c.store_id, store_id)]:
        if value:
            query = query.where(column == value)
    grouped = {}
    fields = ("order_count", "follow_numerator", "follow_denominator", "follow_any_numerator", "follow_any_denominator", "verification_numerator", "verification_denominator")

    def empty(key: str, name: str) -> dict:
        return {"key": key, "name": name, "_stores": set(), **dict.fromkeys(fields, 0)}

    totals = empty("all", "合计")
    key_field, name_field = LEVEL_FIELDS[level]
    for row in _limited_rows(session, query, MAX_REPORT_ROWS, mappings=True):
        key = row[key_field] or "unmapped:" + level
        item = grouped.setdefault(key, empty(key, row[name_field] or "未映射组织"))
        for target in (item, totals):
            metric = row["metric_key"]
            if metric == "eligible_store":
                target["_stores"].add(row["service_store_code"])
            elif metric == "order_count":
                target["order_count"] += row["numerator"]
            elif metric == "follow_24h":
                target["follow_numerator"] += row["numerator"]
                target["follow_denominator"] += row["denominator"]
            elif metric == "follow_any":
                target["follow_any_numerator"] += row["numerator"]
                target["follow_any_denominator"] += row["denominator"]
            elif metric == "self_verification":
                target["verification_numerator"] += row["numerator"]
                target["verification_denominator"] += row["denominator"]

    def finish(item: dict) -> dict:
        complete = item["follow_any_denominator"] == item["follow_denominator"]
        item["follow_rate"] = round(item["follow_any_numerator"] / item["follow_denominator"], 6) if complete and item["follow_denominator"] else None
        if not complete:
            item["follow_any_numerator"] = None
        item["store_count"] = len(item.pop("_stores"))
        for result, num, den in [("order_average", "order_count", "store_count"),
                                 ("follow_24h_rate", "follow_numerator", "follow_denominator"),
                                 ("verification_rate", "verification_numerator", "verification_denominator")]:
            item[result] = round(item[num] / item[den], 6) if item[den] else None
        return item

    rows = [finish(item) for item in grouped.values()]
    rows.sort(key=lambda row: row["name"])
    non_null = [row for row in rows if row[sort_by] is not None]
    non_null.sort(key=lambda row: row[sort_by], reverse=sort_order.upper() != "ASC")
    rows = non_null + [row for row in rows if row[sort_by] is None]
    rank, previous = 0, object()
    for index, row in enumerate(rows, 1):
        if row[sort_by] != previous:
            rank, previous = index, row[sort_by]
        row["rank"] = rank if row[sort_by] is not None else None
    return dict(period_start=period_start, period_end=period_end - timedelta(days=1), level=level,
        total=len(rows), page=page, page_size=page_size, rows=rows[(page - 1)*page_size:page*page_size],
        totals=finish(totals), latest_observed_at=run["observed_through"], metric_definitions=DEFINITIONS,
        data_mode=run["data_mode"], snapshot_id=run["run_id"], eligibility_version=run["eligibility_version"],
        quality_json=run["quality_json"] if scope_store_ids is None else {},
        preview_note=("虚拟测试数据，仅用于验证计算逻辑；有效门店数为测试名单，不是实际1531家。"
                      if run["data_mode"] == "synthetic" else ""))
