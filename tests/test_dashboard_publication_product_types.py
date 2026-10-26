"""Financial product filters retain immutable types across legacy scopes."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event, insert, select, update

from apps.api.dy_api.dashboard_publications import finance
from apps.api.dy_api.dashboard_publications.lifecycle import PublicationError
from apps.api.dy_api.dashboard_publications.schema import metadata, runs


AT = datetime(2026, 10, 26, tzinfo=UTC)
PUBLICATION_ID = "historical-product-types"
HISTORICAL_TYPE = "历史养车服务"


def _seed(session):
    metadata.create_all(session.bind)
    session.execute(insert(runs).values(id=PUBLICATION_ID, module="settlement",
        status="success", cutoff=AT, created_at=AT, published_at=AT, stats_json={}))
    session.execute(insert(finance.dimensions), [
        {"publication_id": PUBLICATION_ID, "kind": "filters", "key": "all", "value": {
            "product_types": ["all", "精诚养车"], "product_scopes": ["all", "旧范围"],
            "product_scope_type_map": {"旧范围": ["精诚养车"]}}},
        {"publication_id": PUBLICATION_ID, "kind": "source", "key": "settlement",
            "value": {"has_generation": True}},
        {"publication_id": PUBLICATION_ID, "kind": "period_readiness", "key": "v1", "value": {
            "schema_version": 1, "months": {"2026-08": {"ready": True}, "2026-09": {"ready": True}}}},
        *[{"publication_id": PUBLICATION_ID, "kind": "store", "key": store_id,
            "value": {"store_id": store_id, "store_name": store_id}} for store_id in ("allowed", "other")],
    ])
    for store_id, product_type in (("allowed", HISTORICAL_TYPE), ("other", "其他门店历史类型")):
        for scope, selected_type, amount, count in (
            ("all", "all", 9007199254740993, 7),
            ("all", product_type, 300, 4),
            ("旧范围A", product_type, 100, 2),
            ("旧范围B", product_type, 200, 3),
        ):
            metrics = {key: 0 for key in finance.MONTH_METRICS}
            metrics.update(sales_order_count=count, sales_amount_cent=amount,
                promotion_original_fee_cent=amount, promotion_net_fee_cent=amount,
                net_settlement_reference_cent=amount)
            lines = [{"statement_line_id": "original-line-A", "product_scope": "旧范围A",
                "product_type": product_type, "fee_direction": "PROMOTION", "net_fee_cent": 100},
                {"statement_line_id": "original-line-B", "product_scope": "旧范围B",
                "product_type": product_type, "fee_direction": "PROMOTION", "net_fee_cent": 200}]
            session.execute(insert(finance.monthly).values(publication_id=PUBLICATION_ID,
                month="2026-09", store_id=store_id, product_scope=scope, product_type=selected_type,
                statement={"statement_id": "original-locked-statement", "statement_status": "LOCKED"},
                lines=lines, **metrics))
            for period in (1, 2):
                session.execute(insert(finance.ranking).values(publication_id=PUBLICATION_ID,
                    period_type=period, period_key="2026-09", store_id=store_id, store_name=store_id,
                    product_scope=scope, product_type=selected_type,
                    **{key: metrics[key] for key in finance.RANK_METRICS}))
    session.commit()


@pytest.mark.parametrize("legacy_scope", ["all", "旧范围A", "旧范围B", "不存在的旧范围"])
def test_frozen_type_reads_cross_scope_canonical_partitions_without_duplicate_counts(db_session, legacy_scope):
    _seed(db_session)
    filters = {"period_key": "2026-09", "product_scope": legacy_scope,
        "product_type": HISTORICAL_TYPE, "scope_store_ids": ("allowed",)}
    ranking = finance.read_store_ranking(db_session, PUBLICATION_ID, filters)
    assert ranking["product_scope"] == "all"
    assert ranking["total"] == 1
    assert ranking["totals"]["sales_order_count"] == 4
    assert ranking["totals"]["promotion_net_fee_cent"] == 300
    monthly = finance.read_monthly_settlement(db_session, PUBLICATION_ID,
        {**filters, "store_id": "allowed", "month": "2026-09"})
    assert monthly["product_scope"] == "all"
    assert monthly["metrics"]["promotion_net_fee_cent"] == 300
    assert monthly["computed_cumulative"]["promotion_net_fee_cent"] == 300
    assert [(line["statement_line_id"], line["product_scope"], line["product_type"])
        for line in monthly["lines"]] == [
            ("original-line-A", "旧范围A", HISTORICAL_TYPE),
            ("original-line-B", "旧范围B", HISTORICAL_TYPE)]
    assert monthly["publication_statement"]["statement_status"] == "LOCKED"


def test_all_amounts_and_current_store_authorization_are_unchanged(db_session):
    _seed(db_session)
    filters = {"period_key": "2026-09", "product_scope": "旧范围A",
        "product_type": "all", "scope_store_ids": ("allowed",)}
    ranked = finance.read_store_ranking(db_session, PUBLICATION_ID, filters)
    assert ranked["totals"]["promotion_net_fee_cent"] == 9007199254740993
    assert ranked["totals"]["sales_order_count"] == 7
    assert finance.read_store_ranking(db_session, PUBLICATION_ID,
        {**filters, "scope_store_ids": ()})["total"] == 0
    unavailable = finance.read_monthly_settlement(db_session, PUBLICATION_ID,
        {**filters, "store_id": "other", "month": "2026-09"})
    assert set(unavailable["metrics"].values()) == {0}
    assert unavailable["lines"] == []


def test_metadata_adds_only_visible_frozen_types_and_never_queries_live_sources(db_session):
    _seed(db_session)
    statements = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        choices = finance.read_filters(db_session, PUBLICATION_ID, scope_store_ids=("allowed",))
        assert choices["product_scopes"] == ["all"]
        assert choices["product_scope_type_map"] == {}
        assert choices["product_types"] == ["all", HISTORICAL_TYPE, "精诚养车"]
        assert HISTORICAL_TYPE not in finance.read_filters(db_session, PUBLICATION_ID,
            scope_store_ids=())["product_types"]
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)
    assert statements and all(statement.lstrip().startswith("SELECT") for statement in statements)
    assert all("FROM dashboard_publication_" in statement for statement in statements)
    assert db_session.scalar(select(finance.dimensions.c.value).where(
        finance.dimensions.c.publication_id == PUBLICATION_ID,
        finance.dimensions.c.kind == "filters"))["product_scopes"] == ["all", "旧范围"]


def test_missing_canonical_type_partition_does_not_invent_cross_scope_distinct(db_session):
    _seed(db_session)
    db_session.execute(finance.ranking.delete().where(finance.ranking.c.product_scope == "all",
        finance.ranking.c.product_type == HISTORICAL_TYPE))
    db_session.execute(finance.monthly.delete().where(finance.monthly.c.product_scope == "all",
        finance.monthly.c.product_type == HISTORICAL_TYPE))
    filters = {"period_key": "2026-09", "product_type": HISTORICAL_TYPE}
    assert finance.read_store_ranking(db_session, PUBLICATION_ID, filters)["total"] == 0
    monthly = finance.read_monthly_settlement(db_session, PUBLICATION_ID,
        {**filters, "store_id": "allowed", "month": "2026-09"})
    assert set(monthly["metrics"].values()) == {0}
    assert monthly["lines"] == []


def test_product_filter_cannot_bypass_frozen_period_readiness(db_session):
    _seed(db_session)
    db_session.execute(update(finance.dimensions).where(finance.dimensions.c.kind == "period_readiness")
        .values(value={"schema_version": 1, "months": {"2026-08": {"ready": False},
            "2026-09": {"ready": True}}}))
    filters = {"period_key": "2026-09", "product_scope": "旧范围A", "product_type": HISTORICAL_TYPE}
    monthly = finance.read_monthly_settlement(db_session, PUBLICATION_ID,
        {**filters, "store_id": "allowed", "month": "2026-09"})
    assert monthly["metrics"]["promotion_net_fee_cent"] == 300
    assert monthly["computed_cumulative"]["promotion_net_fee_cent"] is None
    with pytest.raises(PublicationError) as caught:
        finance.read_store_ranking(db_session, PUBLICATION_ID, {**filters, "period_type": "CUMULATIVE"})
    assert caught.value.code == "PUBLICATION_PERIOD_NOT_READY"
