"""Independent monthly availability, nullable cumulative metrics and HTTP types."""
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, insert, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency
from apps.api.dy_api.dashboard_publications import finance, period_readiness
from apps.api.dy_api.dashboard_publications.lifecycle import PublicationError
from apps.api.dy_api.dashboard_publications.schema import metadata, runs
from apps.api.dy_api.dashboard_publications.sources import MODULE_CONTRACT_VERSIONS
from apps.api.dy_api.models import DimStore


AT = datetime(2026, 10, 21, tzinfo=UTC)
MONTH_FILTERS = {"period_type": "MONTHLY", "period_key": "2026-09",
    "ranking_basis": "PROMOTION_FEE_MONTH", "scope_store_ids": ("allowed",)}
MIXED_AVAILABILITY = {"monthly_ready": True, "cumulative_ready": False,
    "incomplete_months": ["2026-08"]}
CUMULATIVE_FIELDS = {
    "sales_order_count_cumulative", "sales_amount_cumulative_cent",
    "verified_order_count_cumulative", "verified_amount_cumulative_cent",
    "promotion_cumulative_fee_cent", "management_cumulative_fee_cent",
    "net_settlement_reference_cumulative_cent", "sales_order_count", "sales_amount_cent",
    "verified_order_count", "verified_amount_cent",
}


def seed_frozen_monthly(session):
    """Freeze intentionally nonzero partial cumulative rows and complete September."""
    metadata.create_all(session.bind)
    session.execute(insert(runs).values(id="monthly-frozen", module="settlement", status="success",
        cutoff=AT, created_at=AT, published_at=AT, stats_json={
            "contract_version": MODULE_CONTRACT_VERSIONS["settlement"]}))
    session.execute(insert(finance.dimensions), [
        {"publication_id": "monthly-frozen", "kind": "period_readiness", "key": "v1", "value": {
            "schema_version": 1, "months": {"2026-08": {"ready": False}, "2026-09": {"ready": True}}}},
        {"publication_id": "monthly-frozen", "kind": "source", "key": "settlement",
            "value": {"has_generation": True}},
        {"publication_id": "monthly-frozen", "kind": "filters", "key": "all",
            "value": {"product_scope_type_map": {"all": ["all"]}, "product_types": ["all"]}},
        *[{"publication_id": "monthly-frozen", "kind": "store", "key": store_id,
            "value": {"store_id": store_id, "store_name": store_id}}
            for store_id in ("allowed", "other", "zero")],
    ])
    for store_id, factor in (("allowed", 1), ("other", 3), ("zero", 0)):
        session.add(DimStore(store_id=store_id, store_name=store_id))
        # The zero store deliberately has no analytical rows: complete evidence
        # plus no fee facts is a genuine zero, not an unavailable amount.
        if factor == 0:
            continue
        values = {key: factor * (index + 1) for index, key in enumerate(finance.RANK_METRICS)}
        values["promotion_net_fee_cent"] = 12345 * factor
        values["management_net_fee_cent"] = 4321 * factor
        values["net_settlement_reference_cent"] = 8024 * factor
        values["sales_amount_cent"] = 9007199254740993 * factor
        for period in (1, 2):
            session.execute(insert(finance.ranking).values(publication_id="monthly-frozen",
                period_type=period, period_key="2026-09", store_id=store_id, store_name=store_id,
                product_scope="all", product_type="all",
                **{key: amount * period for key, amount in values.items()}))
        session.execute(insert(finance.monthly).values(publication_id="monthly-frozen",
            month="2026-09", store_id=store_id, product_scope="all", product_type="all",
            **({key: 0 for key in finance.MONTH_METRICS} | values), lines=[]))
    session.commit()


def _blocked(call):
    with pytest.raises(PublicationError) as caught:
        call()
    assert (caught.value.code, caught.value.http_status) == ("PUBLICATION_PERIOD_NOT_READY", 503)


def test_monthly_mixed_metrics_null_aliases_scope_and_read_only(db_session, monkeypatch):
    seed_frozen_monthly(db_session)
    monkeypatch.setattr(period_readiness, "capture", lambda *a: pytest.fail("live task scan"))
    statements = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        result = finance.read_store_ranking(db_session, "monthly-frozen", MONTH_FILTERS)
        assert result["period_availability"] == MIXED_AVAILABILITY
        assert result["total"] == 1
        assert result["list"][0]["store_id"] == "allowed"
        for metrics in (result["totals"], result["list"][0]):
            assert all(metrics[key] is None for key in CUMULATIVE_FIELDS)
            assert metrics["promotion_month_fee_cent"] == metrics["promotion_net_fee_cent"] == 12345
            assert metrics["management_month_fee_cent"] == metrics["management_net_fee_cent"] == 4321
            assert metrics["net_settlement_reference_month_cent"] == metrics["net_settlement_reference_cent"] == 8024
        legacy = finance.read_store_ranking(db_session, "monthly-frozen", MONTH_FILTERS | {"ranking_basis": None})
        assert legacy["totals"]["sales_amount_cent"] == 9007199254740993
        assert legacy["period_availability"] == MIXED_AVAILABILITY
        monthly = finance.read_monthly_settlement(db_session, "monthly-frozen",
            {"month": "2026-09", "store_id": "allowed"})
        assert monthly["metrics"]["promotion_net_fee_cent"] == 12345
        assert monthly["computed_cumulative"] == {"promotion_net_fee_cent": None, "management_net_fee_cent": None}
        assert monthly["period_availability"] == MIXED_AVAILABILITY
        denied = finance.read_monthly_settlement(db_session, "monthly-frozen",
            {"month": "2026-09", "store_id": "other", "scope_store_ids": ("allowed",)})
        assert set(denied["metrics"].values()) == {0}
        assert denied["computed_cumulative"] == monthly["computed_cumulative"]
        empty = finance.read_store_ranking(db_session, "monthly-frozen", MONTH_FILTERS | {"scope_store_ids": ()})
        assert empty["list"] == [] and empty["total"] == 0
        assert empty["totals"]["promotion_month_fee_cent"] == 0
        assert empty["totals"]["sales_amount_cent"] is None
        zero = finance.read_monthly_settlement(db_session, "monthly-frozen",
            {"month": "2026-09", "store_id": "zero"})
        assert set(zero["metrics"].values()) == {0}
        assert set(zero["computed_cumulative"].values()) == {None}
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)
    assert statements and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    assert all("job_runs" not in sql.lower() and "raw_douyin" not in sql.lower() for sql in statements)


def test_incomplete_prefix_uses_only_monthly_store_universe(db_session):
    seed_frozen_monthly(db_session)
    db_session.execute(insert(finance.ranking).values(publication_id="monthly-frozen",
        period_type=2, period_key="2026-09", store_id="historical-only", store_name="Historical only",
        product_scope="all", product_type="all", **{key: 999 for key in finance.RANK_METRICS}))
    filters = MONTH_FILTERS | {"scope_store_ids": None}
    mixed = finance.read_store_ranking(db_session, "monthly-frozen", filters)
    plain = finance.read_store_ranking(db_session, "monthly-frozen", filters | {"ranking_basis": None})
    assert mixed["total"] == plain["total"] == 2
    assert {row["store_id"] for row in mixed["list"]} == {"allowed", "other"}
    assert mixed["totals"]["promotion_month_fee_cent"] == plain["totals"]["promotion_net_fee_cent"] == 49380
    db_session.execute(update(finance.dimensions).where(finance.dimensions.c.kind == "period_readiness").values(
        value={"schema_version": 1, "months": {"2026-08": {"ready": True}, "2026-09": {"ready": True}}}))
    complete = finance.read_store_ranking(db_session, "monthly-frozen", filters)
    assert complete["total"] == 3
    assert {row["store_id"] for row in complete["list"]} == {"allowed", "other", "historical-only"}


@pytest.mark.parametrize("extra", [{"period_type": "CUMULATIVE"},
    *[{"ranking_basis": basis} for basis in (
        "SALES_AMOUNT_CUMULATIVE", "VERIFIED_AMOUNT_CUMULATIVE", "PROMOTION_FEE_CUMULATIVE")]])
def test_cumulative_requests_and_sorts_still_fail_closed(db_session, extra):
    seed_frozen_monthly(db_session)
    _blocked(lambda: finance.read_store_ranking(db_session, "monthly-frozen", MONTH_FILTERS | extra))
    _blocked(lambda: finance.export_finance_invoices(db_session, "monthly-frozen",
        month="2026-09", fee_direction="PROMOTION", metric_scope="CUMULATIVE"))


@pytest.mark.parametrize("snapshot", [None, {}, {"schema_version": 2, "months": {"2026-09": {"ready": True}}},
    {"schema_version": 1, "months": {"2026-09": {"ready": "true"}}},
    {"schema_version": 1, "months": {"2026-08": {"ready": True}}}])
def test_invalid_or_missing_metadata_blocks_both_monthly_readers(db_session, snapshot):
    seed_frozen_monthly(db_session)
    evidence = (finance.dimensions.c.publication_id == "monthly-frozen") & (finance.dimensions.c.kind == "period_readiness")
    if snapshot is None:
        db_session.execute(delete(finance.dimensions).where(evidence))
    else:
        db_session.execute(update(finance.dimensions).where(evidence).values(value=snapshot))
    _blocked(lambda: finance.read_store_ranking(db_session, "monthly-frozen", MONTH_FILTERS))
    _blocked(lambda: finance.read_monthly_settlement(db_session, "monthly-frozen",
        {"month": "2026-09", "store_id": "allowed"}))


def assert_monthly_http_contract(session, monkeypatch):
    """Exercise actual SQL aggregation, application route and JSON serialization."""
    seed_frozen_monthly(session)
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setattr(period_readiness, "capture", lambda *a: pytest.fail("GET scanned live tasks"))
    app = create_app()
    identity = [AuthContext(user_id="reader", username="reader", display_name="Reader",
        role="highest_admin", store_ids=(), auth_type="test", page_keys=("C01", "C02"))]
    app.dependency_overrides[get_session_dependency] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: identity[0]
    params = {"publication_id": "monthly-frozen", "periodType": "MONTHLY",
        "periodKey": "2026-09", "rankingBasis": "PROMOTION_FEE_MONTH"}
    with TestClient(app) as client:
        response = client.get("/api/v1/dashboard/store-ranking", params=params)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["periodAvailability"] == {"monthlyReady": True, "cumulativeReady": False,
            "incompleteMonths": ["2026-08"]}
        assert data["totals"]["promotionMonthFeeCent"] == 49380
        for row in [data["totals"], *data["list"]]:
            assert type(row["promotionMonthFeeCent"]) is int
            assert row["salesAmountCumulativeCent"] is None and row["salesAmountCent"] is None
            assert row["verifiedAmountCent"] is None and row["promotionCumulativeFeeCent"] is None
        response = client.get("/api/v1/stores/allowed/monthly-settlement",
            params={"month": "2026-09", "publication_id": "monthly-frozen"})
        assert response.status_code == 200, response.text
        monthly = response.json()["data"]
        assert type(monthly["metrics"]["salesAmountCent"]) is int
        assert monthly["metrics"]["salesAmountCent"] == 9007199254740993
        assert monthly["computedCumulative"] == {"promotionNetFeeCent": None, "managementNetFeeCent": None}
        for extra in ({"periodType": "CUMULATIVE"}, {"rankingBasis": "SALES_AMOUNT_CUMULATIVE"},
                {"periodKey": "2026-08"}):
            blocked = client.get("/api/v1/dashboard/store-ranking", params=params | extra)
            assert blocked.status_code == 503, blocked.text
            assert blocked.json()["detail"]["code"] == "PUBLICATION_PERIOD_NOT_READY"
        identity[0] = replace(identity[0], role="store", store_scope_mode="specified", store_ids=("allowed",))
        scoped = client.get("/api/v1/dashboard/store-ranking", params=params)
        assert scoped.status_code == 200, scoped.text
        assert [row["storeId"] for row in scoped.json()["data"]["list"]] == ["allowed"]
        assert client.get("/api/v1/stores/other/monthly-settlement",
            params={"month": "2026-09", "publication_id": "monthly-frozen"}).status_code == 403
        identity[0] = replace(identity[0], role="highest_admin", store_scope_mode="all", store_ids=())
        session.execute(update(finance.dimensions).where(finance.dimensions.c.kind == "period_readiness").values(
            value={"schema_version": 1, "months": {"2026-08": {"ready": True}, "2026-09": {"ready": True}}}))
        session.commit()
        complete = client.get("/api/v1/dashboard/store-ranking", params=params)
        assert complete.status_code == 200, complete.text
        totals = complete.json()["data"]["totals"]
        assert type(totals["salesAmountCumulativeCent"]) is int
        assert totals["salesAmountCumulativeCent"] == 9007199254740993 * 8
        zero = client.get("/api/v1/stores/zero/monthly-settlement",
            params={"month": "2026-09", "publication_id": "monthly-frozen"})
        assert zero.status_code == 200, zero.text
        assert set(zero.json()["data"]["metrics"].values()) == {0}
        assert set(zero.json()["data"]["computedCumulative"].values()) == {0}
        session.execute(delete(finance.dimensions).where(finance.dimensions.c.kind == "period_readiness"))
        session.commit()
        missing = client.get("/api/v1/dashboard/store-ranking", params=params)
        assert missing.status_code == 503, missing.text
        missing = client.get("/api/v1/stores/allowed/monthly-settlement",
            params={"month": "2026-09", "publication_id": "monthly-frozen"})
        assert missing.status_code == 503, missing.text


def test_monthly_http_numeric_and_null_types(db_session, monkeypatch):
    assert_monthly_http_contract(db_session, monkeypatch)


@pytest.mark.parametrize("global_access", [True, False])
def test_monthly_type_filter_survives_switch_to_empty_authorized_store(db_session, monkeypatch, global_access):
    seed_frozen_monthly(db_session)
    db_session.execute(insert(finance.ranking).values(publication_id="monthly-frozen",
        period_type=1, period_key="2026-09", store_id="allowed", store_name="Allowed",
        product_scope="all", product_type="历史养车服务",
        **{key: 123 for key in finance.RANK_METRICS}))
    db_session.commit()
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    app = create_app()
    identity = [AuthContext(user_id="reader", username="reader", display_name="Reader",
        role="highest_admin" if global_access else "store",
        store_scope_mode="all" if global_access else "specified",
        store_ids=() if global_access else ("allowed", "zero"),
        auth_type="test", page_keys=("C01", "C02"))]
    app.dependency_overrides[get_session_dependency] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: identity[0]
    params = {"month": "2026-09", "publication_id": "monthly-frozen", "productType": "历史养车服务"}
    with TestClient(app) as client:
        empty = client.get("/api/v1/stores/zero/monthly-settlement", params=params)
        assert empty.status_code == 200, empty.text
        assert empty.json()["data"]["productType"] == "历史养车服务"
        assert set(empty.json()["data"]["metrics"].values()) == {0}
        assert empty.json()["data"]["lines"] == []
        unknown = client.get("/api/v1/stores/zero/monthly-settlement",
            params=params | {"productType": "不存在的商品类型"})
        assert unknown.status_code == 422
        # Removing the only store with this historical type must not expose it.
        identity[0] = replace(identity[0], role="store", store_scope_mode="specified", store_ids=("zero",))
        assert client.get("/api/v1/stores/zero/monthly-settlement", params=params).status_code == 422
        assert client.get("/api/v1/stores/allowed/monthly-settlement", params=params).status_code == 403
