"""Sales projection parity, version immutability and access boundaries."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, insert, select, update

from apps.api.dy_api.dashboard_publications import sales
from apps.api.dy_api.dashboard_publications.schema import metadata, runs
from apps.api.dy_api.models import DimSkuProductRule, DimStore, SettlementOrderDetail
from apps.api.dy_api.routes._data import DashboardDataStore


CUTOFF = datetime(2026, 10, 19, tzinfo=timezone.utc)


def prepare_sales(session):
    """Seed cross-period coupon cohorts and two independent publications."""
    metadata.create_all(session.get_bind())
    session.execute(insert(runs), [{"id": value, "module": "sales", "status": "building", "cutoff": CUTOFF,
                                   "created_at": CUTOFF} for value in ("s1", "s2")])
    session.add_all([DimStore(store_id="A", store_name="Alpha"), DimStore(store_id="B", store_name="Beta"),
        DimSkuProductRule(sku_id="sku", product_scope="scope", product_type="P")])
    facts = [
        ("c1", "o1", "P", "A", "2026-01-01", "A", "2026-02-01", True, 100),
        ("c2", "o1", "P", "A", "2026-01-01", "A", "2026-02-03", True, 200),
        ("c3", "o2", "P", "B", "2026-01-03", "A", "2026-02-02", True, 300),
        ("c4", "o3", "P", "A", "2026-02-01", "B", "2026-02-02", True, 400),
        ("c5", "o4", "Q", "A", "2026-01-01", "A", "2026-01-02", False, 500),
        ("c6", "o5", "P", "A", "2025-12-01", "A", "2026-02-04", True, 600),
        ("c7", "o6", "P", "A", "2024-01-01", "A", "2024-01-04", True, 700),
    ]
    for coupon, order, product, sale_store, sale, verify_store, verify, verified, amount in facts:
        session.add(SettlementOrderDetail(coupon_id=coupon, order_id=order, product_type=product,
            sale_store_id=sale_store, sale_time=datetime.fromisoformat(sale).replace(tzinfo=timezone.utc),
            verify_store_id=verify_store, verify_time=datetime.fromisoformat(verify).replace(tzinfo=timezone.utc),
            is_verified=verified, paid_amount_cent=amount, is_refund_excluded=False))
    session.add(SettlementOrderDetail(coupon_id="refund", order_id="refund", product_type="P",
        sale_store_id="A", sale_time=CUTOFF, is_refund_excluded=True))
    session.flush()
    assert sales.build(session, "s1", CUTOFF)["row_count"] == 7
    session.commit()


def assert_sales_parity(session):
    """Compare aggregate contracts against the pre-publication implementation."""
    old = DashboardDataStore(session)
    for store in (None, "A", "B"):
        for month in ("2026-01", "2026-02"):
            expected = old.sales_dashboard(store_id=store, month=month, product_type="all")
            actual = sales.read(session, "s1", store_id=store, month=month, trend_months=[month])
            assert actual["metrics"] == expected["metrics"]
            assert actual["product_rows"] == expected["product_rows"]
            # Datetime serialization differs across the ORM and legacy text SQL.
            def without_times(rows):
                return [{**row, "sample_points": [{k: v for k, v in point.items() if k not in ("sale_time", "verify_time")} for point in row["sample_points"]]} for row in rows]
            assert without_times(actual["cycle_rows"]) == without_times(expected["cycle_rows"])
    january = sales.read(session, "s1", store_id="A", month="2026-01")
    assert january["metrics"]["total_sales_order_count"] == 2
    assert january["metrics"]["self_verify_order_count"] == 1
    february = sales.read(session, "s1", store_id="A", month="2026-02")
    assert february["metrics"]["total_verify_order_count"] == 3
    assert february["metrics"]["actual_verify_amount_cent"] == 1200
    assert february["cycle_rows"][0]["median_days"] == 31
    assert february["cycle_rows"][0]["q1_days"] == 30.5
    assert sales.read(session, "s1", year=2024)["metrics"]["total_sales_order_count"] == 1
    assert sales.read(session, "s1", year=2026)["metrics"]["total_sales_order_count"] == 4
    assert sales.read(session, "s1", month="history")["metrics"]["total_sales_order_count"] == 6
    assert sales.read(session, "s1", scope_store_ids=[])["metrics"]["total_sales_order_count"] == 0
    assert sales.read(session, "s1", product_scope="missing")["product_rows"] == []
    assert sales.read(session, "s1", visible_product_types=[])["cycle_rows"] == []
    # The selected month no longer limits the source of an explicitly wider trend.
    trend = sales.read(session, "s1", store_id="A", month="2026-02", trend_months=["2026-01"])["trend_rows"]
    assert next(row for row in trend if row["month"] == "2026-01")["order_count"] == 2


def test_sales_parity_and_boundaries(db_session):
    prepare_sales(db_session)
    assert_sales_parity(db_session)


def test_sales_versions_and_read_only_queries(db_session, monkeypatch):
    prepare_sales(db_session)
    before = sales.read(db_session, "s1", month="history")
    db_session.execute(update(SettlementOrderDetail).values(paid_amount_cent=9999, is_verified=False))
    sales.build(db_session, "s2", CUTOFF)
    db_session.commit()
    assert sales.read(db_session, "s1", month="history") == before
    assert sales.read(db_session, "s2", month="history")["metrics"]["total_verify_order_count"] == 0
    monkeypatch.setattr(sales, "build", lambda *args: pytest.fail("read called builder"))
    statements = []
    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        sales.read(db_session, "s1", month="history")
        filters = sales.read_filters(db_session, "s1", scope_store_ids=["A"])
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)
    assert filters["years"] == [2026, 2025, 2024]
    assert filters["stores"] == [{"store_id": "A", "store_name": "Alpha"}]
    assert all(statement.lstrip().upper().startswith(("SELECT", "WITH")) for statement in statements)
    assert all("settlement_order_details" not in statement and "dim_stores" not in statement for statement in statements)


def test_cycle_quantiles_and_sample_cap_are_order_based(db_session):
    prepare_sales(db_session)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for number in range(111):
        db_session.add(SettlementOrderDetail(coupon_id=f"sample-{number}", order_id=f"sample-{number}",
            product_type="sample", sale_store_id="A", verify_store_id="A", sale_time=start,
            verify_time=start + timedelta(hours=number), is_verified=True, paid_amount_cent=1))
    db_session.flush()
    sales.build(db_session, "s2", CUTOFF)
    actual = sales.read(db_session, "s2", product_type="sample", month="2026-01")["cycle_rows"][0]
    expected = DashboardDataStore(db_session).sales_dashboard(store_id=None, month="2026-01", product_type="sample")["cycle_rows"][0]
    assert actual["count"] == 111
    assert len(actual["sample_points"]) == 90
    for field in ("min_days", "q1_days", "median_days", "q3_days", "max_days", "avg_days"):
        assert actual[field] == expected[field]
    assert [point["order_id"] for point in actual["sample_points"]] == [point["order_id"] for point in expected["sample_points"]]


def assert_cross_product_order_aggregation(session):
    """One order in two products still counts once globally, with shortest cycle."""
    session.add(SettlementOrderDetail(coupon_id="cross-product", order_id="o1", product_type="Q", sale_store_id="A",
        verify_store_id="A", sale_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        verify_time=datetime(2026, 2, 5, tzinfo=timezone.utc), is_verified=True, paid_amount_cent=50))
    for number, order in enumerate(("éclair", "E", "中", "Å")):
        session.add(SettlementOrderDetail(coupon_id=f"unicode-{number}", order_id=order, product_type="Unicode",
            sale_store_id="A", verify_store_id="A", sale_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            verify_time=datetime(2026, 1, 2, tzinfo=timezone.utc), is_verified=True, paid_amount_cent=1))
    for coupon, order, hours, days in (("precise-1", "precise-1", 0, 1.0049),
        ("precise-1b", "precise-1", 1, 1.0048), ("precise-2", "precise-2", 0, 1.0049),
        ("precise-3", "precise-3", 0, 1.0149)):
        sale_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hours)
        session.add(SettlementOrderDetail(coupon_id=coupon, order_id=order, product_type="Precision",
            sale_store_id="A", verify_store_id="A", sale_time=sale_at,
            verify_time=sale_at + timedelta(days=days), is_verified=True, paid_amount_cent=1))
    session.flush()
    sales.build(session, "s2", CUTOFF)
    actual = sales.read(session, "s2", month="history")
    expected = DashboardDataStore(session).sales_dashboard(store_id=None, month="all", product_type="all")
    assert actual["metrics"] == expected["metrics"]
    assert actual["product_rows"] == expected["product_rows"]
    precision_metrics = next(row for row in actual["product_rows"] if row["product_type"] == "Precision")
    precision_cycle = next(row for row in actual["cycle_rows"] if row["product_type"] == "Precision")
    assert precision_metrics["avg_verify_cycle_days"] == 1.01
    assert precision_cycle["avg_days"] == 1.0
    tie_point = next(point for point in precision_cycle["sample_points"] if point["order_id"] == "precise-1")
    assert tie_point["sale_time"].hour == 0
    actual_points = next(row for row in actual["cycle_rows"] if row["product_type"] == "Unicode")["sample_points"]
    assert [point["order_id"] for point in actual_points] == sorted(("éclair", "E", "中", "Å"))


def test_cross_product_order_deduplication(db_session):
    prepare_sales(db_session)
    assert_cross_product_order_aggregation(db_session)
