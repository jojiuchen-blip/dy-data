"""Interpret ranking business evidence only in the background builder."""
from bisect import bisect_right
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased, load_only

from apps.api.dy_api.dashboard_publications import ranking_schema as frozen
from apps.api.dy_api.models import (
    ClueAssignmentRound, ClueCenterOrder, DimAwemeAccount, DimSkuProductRule,
    DimStorePoiMapping, RawAwemeBinding, RawDouyinClue, RawDouyinOrder,
    RawDouyinOrderCoupon, RawDouyinVerifyRecord,
)
from apps.api.dy_api.ranking_identity import OrderAttributionIndex
from apps.api.dy_api.ranking_legacy_followup import bulk_evaluate_legacy_ranking_followup
from apps.api.dy_api.ranking_schema_v1 import eligibility, lead_bindings, org_history
from apps.api.dy_api.ranking_snapshots import utc

BATCH_SIZE = 500
DIMENSION_LIMIT = 250000


def _analyze_projection(session: Session) -> None:
    """Publish usable planner statistics with the facts, before any first read."""
    if session.get_bind().dialect.name == "postgresql":
        for table in (frozen.orders, frozen.rounds, frozen.organizations, frozen.eligibility, frozen.info):
            session.execute(text("ANALYZE " + table.name))


def _dimensions(session, statement):
    rows = list(session.scalars(statement.limit(DIMENSION_LIMIT + 1)))
    if len(rows) > DIMENSION_LIMIT:
        raise ValueError("榜单归属维度超过构建上限，请核对账号绑定")
    return rows


def _copy(session, source, target, publication_id, predicate, columns):
    count = 0
    statement = select(source).where(predicate).execution_options(yield_per=BATCH_SIZE)
    for batch in session.execute(statement).mappings().partitions(BATCH_SIZE):
        values = [{"publication_id": publication_id, **{key: row[key] for key in columns}} for row in batch]
        session.execute(target.insert(), values)
        count += len(values)
    return count


def _unique_poi_stores(poi_rows):
    """Match SQL COUNT(DISTINCT store_id) = 1, including repeated mappings."""
    stores_by_poi = {}
    for poi_id, store_id in poi_rows:
        if poi_id is not None and store_id is not None:
            stores_by_poi.setdefault(poi_id, set()).add(store_id)
    return {poi_id: next(iter(stores)) for poi_id, stores in stores_by_poi.items() if len(stores) == 1}


def _verification_by_store(session, order_ids, poi_to_store, cutoff):
    # Restrict coupons to this order batch before aggregating. Joining the POI
    # dimension here can make PG scan all verifications for each round batch.
    by_store = {}
    statement = select(RawDouyinOrderCoupon.order_id, RawDouyinVerifyRecord.poi_id,
        func.max(RawDouyinVerifyRecord.verify_time)).join(RawDouyinVerifyRecord,
        RawDouyinVerifyRecord.coupon_id == RawDouyinOrderCoupon.coupon_id).where(
        RawDouyinOrderCoupon.order_id.in_(order_ids),
        RawDouyinVerifyRecord.verify_status.in_(("1", "success", "verified", "已核销")),
        RawDouyinVerifyRecord.verify_time <= cutoff,
        or_(RawDouyinVerifyRecord.cancel_time.is_(None), RawDouyinVerifyRecord.cancel_time > cutoff)
    ).group_by(RawDouyinOrderCoupon.order_id, RawDouyinVerifyRecord.poi_id)
    for order_id, poi_id, at in session.execute(statement):
        store_id = poi_to_store.get(poi_id)
        if store_id is not None:
            key, at = (order_id, store_id), utc(at)
            if key not in by_store or at > by_store[key]:
                by_store[key] = at
    return by_store


def build(session: Session, publication_id: str, cutoff: datetime) -> dict[str, Any]:
    """Freeze all observed history in bounded batches without committing.

    Args:
        session: Caller-owned consistent source transaction.
        publication_id: Existing unpublished publication run.
        cutoff: Inclusive observation cutoff.

    Returns:
        Row counts and unknown source coverage; the caller publishes atomically.
    """
    cutoff = utc(cutoff)
    if session.scalar(select(frozen.info.c.publication_id).where(frozen.info.c.publication_id == publication_id)):
        raise ValueError("榜单发布ID已构建")
    # Validate source version consistency before creating any projection rows.
    timeline = {}
    for version, effective in session.execute(select(org_history.c.mapping_version, org_history.c.effective_from).distinct()):
        at = utc(effective)
        if version in timeline and timeline[version] != at:
            raise ValueError("mapping version has inconsistent effective dates")
        timeline[version] = at
    if len(set(timeline.values())) != len(timeline):
        raise ValueError("mapping versions have ambiguous effective dates")
    dates_versions = sorted((at, version) for version, at in timeline.items() if at <= cutoff)
    dates = [item[0] for item in dates_versions]

    def version_at(at):
        index = bisect_right(dates, utc(at)) - 1
        return dates_versions[index][1] if index >= 0 else None

    session.execute(frozen.info.insert().values(publication_id=publication_id, cutoff=cutoff))
    org_count = _copy(session, org_history, frozen.organizations, publication_id,
        org_history.c.effective_from <= cutoff,
        [column.name for column in frozen.organizations.c if column.name != "publication_id"])
    eligibility_count = _copy(session, eligibility, frozen.eligibility, publication_id,
        eligibility.c.product_scope == "精诚养车",
        ("eligibility_version", "service_store_code", "effective_from"))
    sku_rules = _dimensions(session, select(DimSkuProductRule).where(DimSkuProductRule.product_scope == "精诚养车"))
    skus = {row.sku_id for row in sku_rules}
    products = skus | {row.product_id for row in sku_rules if row.product_id}
    poi_rows = list(session.execute(select(DimStorePoiMapping.poi_id, DimStorePoiMapping.store_id).limit(DIMENSION_LIMIT + 1)))
    if len(poi_rows) > DIMENSION_LIMIT:
        raise ValueError("榜单POI维度超过构建上限，请核对门店映射")
    unique_pois = _unique_poi_stores(poi_rows)
    owner_index = OrderAttributionIndex(accounts=_dimensions(session, select(DimAwemeAccount)),
        bindings=_dimensions(session, select(RawAwemeBinding)), poi_to_store=poi_rows)
    sale_time = func.coalesce(RawDouyinOrder.sale_time, RawDouyinOrder.pay_time)
    order_count, last_id = 0, None
    while True:
        statement = select(RawDouyinOrder).where(sale_time <= cutoff).order_by(RawDouyinOrder.id).limit(BATCH_SIZE).options(load_only(
            RawDouyinOrder.id, RawDouyinOrder.order_id, RawDouyinOrder.sku_id, RawDouyinOrder.sale_time,
            RawDouyinOrder.pay_time, RawDouyinOrder.owner_account_id, RawDouyinOrder.owner_douyin_uid, RawDouyinOrder.owner_account_name))
        if last_id is not None:
            statement = statement.where(RawDouyinOrder.id > last_id)
        batch = list(session.scalars(statement))
        if not batch:
            break
        values = []
        for order in batch:
            at = utc(order.sale_time or order.pay_time)
            owner = owner_index.resolve(occurred_at=at, owner_account_id=order.owner_account_id,
                owner_douyin_uid=order.owner_douyin_uid, owner_account_name=order.owner_account_name)
            values.append(dict(publication_id=publication_id, order_id=order.order_id, occurred_at=at,
                store_id=owner.store_id, is_jingcheng=order.sku_id in skus,
                reason=None if owner.store_id else owner.reason, historical_unverified=owner.historical_period_unverified))
        session.execute(frozen.orders.insert(), values)
        order_count += len(values)
        last_id = batch[-1].id

    # Membership stays identical to the old three-source EXISTS rule.
    known_order = select(RawDouyinOrder.order_id).where(RawDouyinOrder.order_id == ClueAssignmentRound.order_id,
        RawDouyinOrder.sku_id.in_(skus)).correlate(ClueAssignmentRound).exists()
    known_raw = select(RawDouyinClue.order_id).where(RawDouyinClue.order_id == ClueAssignmentRound.order_id,
        RawDouyinClue.product_id.in_(products)).correlate(ClueAssignmentRound).exists()
    known_center = select(ClueCenterOrder.order_id).where(ClueCenterOrder.order_id == ClueAssignmentRound.order_id,
        ClueCenterOrder.product_id.in_(products)).correlate(ClueAssignmentRound).exists()
    first_round = aliased(ClueAssignmentRound)
    has_lead = and_(ClueAssignmentRound.lead_key.is_not(None), ClueAssignmentRound.lead_key != "")
    no_lead = or_(ClueAssignmentRound.lead_key.is_(None), ClueAssignmentRound.lead_key == "")
    first_at = select(func.min(first_round.assigned_at)).where(
        first_round.execution_mode == "formal", first_round.assigned_at <= cutoff,
        or_(and_(has_lead, first_round.lead_key == ClueAssignmentRound.lead_key),
            and_(no_lead, or_(first_round.lead_key.is_(None), first_round.lead_key == ""),
                first_round.order_id == ClueAssignmentRound.order_id))
    ).correlate(ClueAssignmentRound).scalar_subquery()
    round_count, last_round = 0, None
    while True:
        statement = select(ClueAssignmentRound, or_(known_order, known_raw, known_center), first_at).where(
            ClueAssignmentRound.execution_mode == "formal", ClueAssignmentRound.assigned_at <= cutoff
        ).order_by(ClueAssignmentRound.assignment_round_id).limit(BATCH_SIZE).options(load_only(
            ClueAssignmentRound.assignment_round_id, ClueAssignmentRound.order_id, ClueAssignmentRound.lead_key,
            ClueAssignmentRound.assigned_at, ClueAssignmentRound.assigned_store_id, ClueAssignmentRound.execution_mode,
            ClueAssignmentRound.metric_follow_24h_start_at, ClueAssignmentRound.round_no,
            ClueAssignmentRound.verified_store_id, ClueAssignmentRound.verified_at, ClueAssignmentRound.updated_at,
            raiseload=True))
        if last_round is not None:
            statement = statement.where(ClueAssignmentRound.assignment_round_id > last_round)
        batch = list(session.execute(statement))
        if not batch:
            break
        rows = [item[0] for item in batch]
        lead_keys = {row.lead_key or "order:" + row.order_id for row in rows}
        pinned = {row["lead_key"]: row for row in session.execute(select(lead_bindings).where(
            lead_bindings.c.lead_key.in_(lead_keys))).mappings()}
        pinned.update({row["lead_key"]: row for row in session.execute(select(frozen.lead_bindings).where(
            frozen.lead_bindings.c.lead_key.in_(lead_keys))).mappings()})
        new_bindings = {}
        for row, _, earliest_at in batch:
            key = row.lead_key or "order:" + row.order_id
            binding = pinned.get(key)
            version = binding["mapping_version"] if binding else version_at(earliest_at)
            if version:
                new_bindings[key] = dict(lead_key=key, first_assigned_at=binding["first_assigned_at"] if binding else earliest_at,
                    mapping_version=version)
        if new_bindings:
            insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
            session.execute(insert(frozen.lead_bindings).on_conflict_do_nothing(index_elements=["lead_key"]),
                list(new_bindings.values()))
            pinned.update({row["lead_key"]: row for row in session.execute(select(frozen.lead_bindings).where(
                frozen.lead_bindings.c.lead_key.in_(lead_keys))).mappings()})
        follow = bulk_evaluate_legacy_ranking_followup(session, {row.order_id for row in rows}, round_rows=rows, observed_through=cutoff)
        verify = _verification_by_store(session, {row.order_id for row in rows}, unique_pois, cutoff)
        values = []
        for row, member, earliest_at in batch:
            key = row.lead_key or "order:" + row.order_id
            binding = pinned.get(key)
            version = binding["mapping_version"] if binding else version_at(earliest_at)
            metric = follow[row.assignment_round_id]
            at = utc(row.assigned_at)
            verified_at = verify.get((row.order_id, row.assigned_store_id))
            values.append(dict(publication_id=publication_id, round_id=row.assignment_round_id, order_id=row.order_id,
                lead_key=key, store_id=row.assigned_store_id, mapping_version=version, assigned_at=at,
                is_jingcheng=bool(member), follow_24h=metric.numerator, follow_any=metric.follow_any_numerator,
                self_verified=int(verified_at is not None and verified_at >= at), under_observation=metric.under_observation,
                first_assignment_changed=bool(binding and utc(binding["first_assigned_at"]) != utc(earliest_at))))
        session.execute(frozen.rounds.insert(), values)
        round_count += len(values)
        last_round = rows[-1].assignment_round_id
    _analyze_projection(session)
    return dict(row_count=order_count + round_count + org_count + eligibility_count,
        orders=order_count, rounds=round_count, organizations=org_count, eligibility=eligibility_count, data_as_of=None)
