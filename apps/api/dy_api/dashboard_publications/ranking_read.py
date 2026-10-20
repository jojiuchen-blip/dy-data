"""SQL filtering and aggregation of already interpreted ranking facts."""
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, literal, select, union_all
from sqlalchemy.orm import Session

from apps.api.dy_api.clue_product_scope import PRODUCT_SCOPE_LABELS, scope_predicate
from apps.api.dy_api.dashboard_publications.ranking_schema import eligibility, info, orders, organizations, rounds
from apps.api.dy_api.ranking_snapshots import DEFINITIONS, LEVEL_FIELDS, sort_ranking_rows, utc

FIELDS = ("order_count", "follow_numerator", "follow_denominator", "follow_any_numerator",
    "follow_any_denominator", "follow_action_numerator", "follow_action_denominator",
    "verification_numerator", "verification_denominator")


def _finish(item):
    # PostgreSQL SUM(bigint) returns Decimal. Keep the count/ratio contract
    # numeric before camelize preserves other domains' Decimal values as text.
    for field in (*FIELDS, "store_count"):
        item[field] = int(item[field])
    for result, numerator, denominator in (("order_average", "order_count", "store_count"),
        ("follow_rate", "follow_any_numerator", "follow_any_denominator"),
        ("follow_action_rate", "follow_action_numerator", "follow_action_denominator"),
        ("follow_24h_rate", "follow_numerator", "follow_denominator"),
        ("verification_rate", "verification_numerator", "verification_denominator")):
        item[result] = round(item[numerator] / item[denominator], 6) if item[denominator] else None
    return item


def read_report(
    session: Session, publication_id: str, *, period_start: datetime, period_end: datetime,
    level: str = "group", scope_store_ids: tuple[str, ...] | None = None,
    group_name: str | None = None, service_center_name: str | None = None,
    district_name: str | None = None, area_name: str | None = None, store_id: str | None = None,
    page: int = 1, page_size: int | None = 50, sort_by: str = "order_count", sort_order: str = "DESC",
    product_scope: str = "jingcheng",
) -> dict[str, Any]:
    """Read one immutable publication using an exclusive end and current scope.

    No source business tables or builders are accessed. SQL reduces the frozen
    facts to organization groups before any rows are materialized in Python.
    """
    if level not in LEVEL_FIELDS or sort_by not in {"order_count", "order_average", "follow_24h_rate", "verification_rate"}:
        raise ValueError("invalid level or sort")
    if page < 1 or (page_size is not None and page_size < 1):
        raise ValueError("invalid pagination")
    start, end = utc(period_start), utc(period_end)
    cutoff = session.scalar(select(info.c.cutoff).where(info.c.publication_id == publication_id))
    if cutoff is None:
        raise ValueError("该版本尚未生成指标数据")
    cutoff = utc(cutoff)
    if start >= end or start > cutoff:
        raise ValueError("invalid period")
    pub_org = organizations.c.publication_id == publication_id
    version = session.scalar(select(organizations.c.mapping_version).where(pub_org,
        organizations.c.effective_from <= start).order_by(organizations.c.effective_from.desc()).limit(1))
    if version is None:
        raise ValueError("no mapping version at roster date")
    eligible_version = session.scalar(select(eligibility.c.eligibility_version).where(
        eligibility.c.publication_id == publication_id, eligibility.c.effective_from <= start
    ).order_by(eligibility.c.effective_from.desc(), eligibility.c.eligibility_version.desc()).limit(1))
    if eligible_version is None:
        raise ValueError("所选日期缺少精诚养车适用门店名单，请先由管理员导入")
    eligible = select(eligibility.c.service_store_code).where(eligibility.c.publication_id == publication_id,
        eligibility.c.eligibility_version == eligible_version).distinct().subquery("eligible_codes")
    roster = select(organizations).where(pub_org, organizations.c.mapping_version == version).subquery("sales_roster")
    # Reject incomplete configuration rather than return partial denominators.
    invalid_eligibility = session.scalar(select(func.count()).select_from(eligibility).where(
        eligibility.c.publication_id == publication_id, eligibility.c.eligibility_version == eligible_version,
        eligibility.c.effective_from > start))
    missing = session.scalar(select(func.count()).select_from(eligible.outerjoin(roster,
        eligible.c.service_store_code == roster.c.service_store_code)).where(roster.c.store_id.is_(None)))
    duplicate = session.execute(select(roster.c.service_store_code).where(
        roster.c.service_store_code.in_(select(eligible))).group_by(roster.c.service_store_code).having(func.count() > 1).limit(1)).first()
    if invalid_eligibility or missing or duplicate:
        raise ValueError("eligible stores are missing or ambiguous organization records")

    key_field, name_field = LEVEL_FIELDS[level]

    def filtered(statement, org):
        if scope_store_ids is not None:
            statement = statement.where(org.c.store_id.in_(scope_store_ids))
        for field, value in (("group_name", group_name), ("service_center_name", service_center_name),
            ("district_name", district_name), ("area_name", area_name), ("store_id", store_id)):
            if value:
                statement = statement.where(org.c[field] == value)
        return statement

    def fragment(source, org, values, code=None):
        statement = select(func.coalesce(org.c[key_field], literal("unmapped:" + level)).label("key"),
            func.coalesce(org.c[name_field], literal("未映射组织")).label("name"),
            (code if code is not None else literal(None)).label("service_store_code"),
            *[(values.get(field, literal(0))).label(field) for field in FIELDS]).select_from(source)
        return filtered(statement, org)

    eligible_fragment = fragment(roster, roster, {}, roster.c.service_store_code).where(
        roster.c.service_store_code.in_(select(eligible)))
    selected_orders = select(orders).where(orders.c.publication_id == publication_id,
        orders.c.occurred_at >= start, orders.c.occurred_at < end,
        scope_predicate(product_scope, orders.c.is_jingcheng)).cte("selected_orders")
    sales_source = selected_orders.join(roster, selected_orders.c.store_id == roster.c.store_id)
    # Sales are unique frozen orders. Fold additive counts before the UNION so
    # global rankings do not sort a wide fragment once for every source order.
    sales_fragment = fragment(sales_source, roster, {"order_count": func.count()}).where(
        selected_orders.c.reason.is_(None)).group_by(roster.c[key_field], roster.c[name_field])

    # All rounds remain available. Query-dependent earliest responsibility is
    # selected after date/product filtering, never by adding daily distincts.
    partition = (rounds.c.order_id, rounds.c.store_id)
    selected_rounds = select(rounds,
        func.row_number().over(partition_by=partition, order_by=(rounds.c.assigned_at, rounds.c.round_id)).label("position"),
        func.min(func.coalesce(rounds.c.mapping_version, literal(""))).over(partition_by=partition).label("min_version"),
        func.max(func.coalesce(rounds.c.mapping_version, literal(""))).over(partition_by=partition).label("max_version")
    ).where(rounds.c.publication_id == publication_id, rounds.c.assigned_at >= start, rounds.c.assigned_at < end,
        scope_predicate(product_scope, rounds.c.is_jingcheng)).cte("selected_rounds")
    responsibility_org = select(organizations).where(pub_org).subquery("responsibility_org")
    responsibility_source = selected_rounds.join(responsibility_org, and_(
        selected_rounds.c.mapping_version == responsibility_org.c.mapping_version,
        selected_rounds.c.store_id == responsibility_org.c.store_id))
    follow_fragment = fragment(responsibility_source, responsibility_org, {
        "follow_numerator": selected_rounds.c.follow_24h, "follow_denominator": literal(1),
        "follow_any_numerator": selected_rounds.c.follow_any, "follow_any_denominator": literal(1),
        "follow_action_numerator": selected_rounds.c.follow_any, "follow_action_denominator": literal(1)})
    self_fragment = fragment(responsibility_source, responsibility_org, {
        "verification_numerator": selected_rounds.c.self_verified, "verification_denominator": literal(1)}).where(
            selected_rounds.c.position == 1, selected_rounds.c.min_version == selected_rounds.c.max_version)
    fragments = union_all(eligible_fragment, sales_fragment, follow_fragment, self_fragment).cte("ranking_fragments")
    aggregates = [func.sum(fragments.c[field]).label(field) for field in FIELDS]
    store_count = func.count(func.distinct(fragments.c.service_store_code)).label("store_count")
    statements = [select(literal("group").label("kind"), fragments.c.key,
        func.min(fragments.c.name).label("name"), store_count, *aggregates).group_by(fragments.c.key)]

    def quality_statement(kind, source, values, key=None):
        return select(literal(kind).label("kind"), (key if key is not None else literal("")).label("key"),
            literal("").label("name"), literal(0).label("store_count"),
            *[values.get(field, literal(0)).label(field) for field in FIELDS]).select_from(source)

    if scope_store_ids is None:
        orders_with_org = selected_orders.outerjoin(roster, selected_orders.c.store_id == roster.c.store_id).outerjoin(
            eligible, roster.c.service_store_code == eligible.c.service_store_code)
        quality_reason = case((selected_orders.c.reason.is_not(None), selected_orders.c.reason),
            (roster.c.store_id.is_(None), literal("missing_historical_store_mapping")))
        statements.append(quality_statement("order_quality", orders_with_org, {
            "order_count": func.count(),
            "follow_numerator": func.sum(case((selected_orders.c.historical_unverified, 1), else_=0)),
            "follow_denominator": func.sum(case((and_(selected_orders.c.reason.is_(None), roster.c.store_id.is_not(None),
                eligible.c.service_store_code.is_(None)), 1), else_=0)),
        }, key=quality_reason).group_by(selected_orders.c.reason, roster.c.store_id.is_(None)))
        missing_org = responsibility_org.c.store_id.is_(None)
        uniform = selected_rounds.c.min_version == selected_rounds.c.max_version
        earliest = selected_rounds.c.position == 1
        quality_source = selected_rounds.outerjoin(responsibility_org, and_(
            selected_rounds.c.mapping_version == responsibility_org.c.mapping_version,
            selected_rounds.c.store_id == responsibility_org.c.store_id))
        statements.append(quality_statement("round_quality", quality_source, {
            "order_count": func.sum(case((missing_org, 3), else_=0) + case((and_(missing_org, earliest, uniform), 1), else_=0)),
            "follow_numerator": func.sum(case((and_(earliest, ~uniform), 1), else_=0)),
            "follow_denominator": func.sum(case((selected_rounds.c.under_observation, 1), else_=0)),
            "follow_any_numerator": func.count(func.distinct(case((selected_rounds.c.first_assignment_changed, selected_rounds.c.lead_key)))),
        }))

    # One SQL shares the date-filtered CTEs across ranking and quality. Only
    # organization groups and a few quality counters reach application memory.
    quality, rows = {}, []

    def record(reason, value):
        if reason and value:
            quality[reason] = quality.get(reason, 0) + int(value)

    for result in session.execute(union_all(*statements) if len(statements) > 1 else statements[0]).mappings():
        row = dict(result)
        kind = row.pop("kind")
        if kind == "group":
            rows.append(_finish(row))
        elif kind == "order_quality":
            record(row["key"], row["order_count"])
            record("orders_historical_binding_unverified", row["follow_numerator"])
            record("orders_outside_eligibility", row["follow_denominator"])
        else:
            record("missing_historical_store_mapping", row["order_count"])
            record("conflicting_responsibility_versions", row["follow_numerator"])
            record("follow_rounds_under_observation", row["follow_denominator"])
            record("first_assignment_changed_requires_review", row["follow_any_numerator"])
    rows = sort_ranking_rows(rows, sort_by, sort_order)
    # Each eligible code belongs to exactly one period-start roster group, so
    # these grouped counts and metric numerators/denominators are additive.
    totals = _finish(dict(key="all", name="合计", **{
        field: sum(row[field] for row in rows) for field in (*FIELDS, "store_count")}))
    return dict(period_start=period_start, period_end=period_end - timedelta(days=1), level=level,
        total=len(rows), page=page, page_size=page_size,
        rows=rows if page_size is None else rows[(page - 1) * page_size:page * page_size], totals=totals,
        latest_observed_at=cutoff, product_scope=product_scope,
        metric_definitions={**DEFINITIONS, "order_count": DEFINITIONS["order_count"].replace("精诚养车", PRODUCT_SCOPE_LABELS[product_scope])},
        data_mode="business", snapshot_id=publication_id, eligibility_version=eligible_version,
        quality_json=quality, preview_note="")


def read_levels(session: Session, publication_id: str, **filters: Any) -> dict[str, dict[str, Any]]:
    """Return all export levels from the same frozen publication and filters."""
    filters = {key: value for key, value in filters.items() if key not in {"level", "page", "page_size"}}
    return {level: read_report(session, publication_id, level=level, page=1, page_size=None, **filters) for level in LEVEL_FIELDS}


def read_filters(
    session: Session, publication_id: str, *, scope_store_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Read month and current organization choices from one frozen publication.

    Organization choices use the mapping effective at the publication cutoff;
    reports continue selecting historical mapping by their query start date.
    Product types and verification dates are absent from this narrow projection
    and are represented by empty choices, never read from mutable source data.
    """
    cutoff = session.scalar(select(info.c.cutoff).where(info.c.publication_id == publication_id))
    if cutoff is None:
        raise ValueError("该版本尚未生成指标数据")
    version = session.scalar(select(organizations.c.mapping_version).where(
        organizations.c.publication_id == publication_id, organizations.c.effective_from <= utc(cutoff)
    ).order_by(organizations.c.effective_from.desc()).limit(1))
    fields = ("store_id", "store_name", "service_store_code", "group_key", "group_name",
        "service_center_key", "service_center_name", "district_key", "district_name", "area_key", "area_name")
    org_query = select(*[organizations.c[field] for field in fields]).where(
        organizations.c.publication_id == publication_id, organizations.c.mapping_version == version
    ).order_by(organizations.c.store_name, organizations.c.store_id)
    # Aggregate months in the database, including Shanghai's month boundary.
    month = (func.to_char(func.timezone("Asia/Shanghai", orders.c.occurred_at), "YYYY-MM")
        if session.bind.dialect.name == "postgresql" else func.strftime("%Y-%m", orders.c.occurred_at, "+8 hours"))
    month_query = select(month.label("month")).where(orders.c.publication_id == publication_id).distinct().order_by(month.desc())
    if scope_store_ids is not None:
        org_query = org_query.where(organizations.c.store_id.in_(scope_store_ids))
        month_query = month_query.where(orders.c.store_id.in_(scope_store_ids))
    org_rows = [dict(row) for row in session.execute(org_query).mappings()]
    months = [value for value in session.scalars(month_query) if value]
    return dict(snapshot_id=publication_id, stores=[{field: row[field] for field in ("store_id", "store_name")} for row in org_rows],
        organizations=org_rows,
        **{field + "s": sorted({row[field] for row in org_rows if row[field]})
            for field in ("group_name", "service_center_name", "district_name", "area_name")},
        sale_months=months, years=sorted({int(value[:4]) for value in months}, reverse=True),
        product_scopes=list(PRODUCT_SCOPE_LABELS), product_types=[],
        product_scope_type_map={scope: [] for scope in PRODUCT_SCOPE_LABELS},
        default_product_type="all", default_product_scope="all", verify_months=[], timezone="Asia/Shanghai")
