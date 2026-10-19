"""Opt-in PostgreSQL checks in a per-test disposable schema."""

import os
import json
from time import perf_counter
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.dashboard_publications import sales
from apps.api.dy_api.dashboard_publications import clues
from apps.api.dy_api.dashboard_publications.schema import runs
from apps.api.dy_api.models import Base, SettlementOrderDetail
from test_dashboard_publication_sales import CUTOFF, prepare_sales, assert_sales_parity, assert_cross_product_order_aggregation


@pytest.fixture()
def publication_postgres_session():
    """Own one schema without touching other collaborators' test data."""
    url = os.getenv("DYDATA_PUBLICATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set DYDATA_PUBLICATION_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database.endswith("_test")
    namespace = "publication_projection_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{namespace}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={namespace}"})
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
        admin.dispose()


def test_sales_projection_on_postgresql(publication_postgres_session):
    prepare_sales(publication_postgres_session)
    assert_sales_parity(publication_postgres_session)


def test_cross_product_orders_and_unicode_sort_on_postgresql(publication_postgres_session):
    prepare_sales(publication_postgres_session)
    assert_cross_product_order_aggregation(publication_postgres_session)


def test_shanghai_month_and_projection_cascade(publication_postgres_session):
    session = publication_postgres_session
    prepare_sales(session)
    session.add(SettlementOrderDetail(coupon_id="tz", order_id="tz", product_type="timezone", sale_store_id="A",
        sale_time=datetime(2026, 1, 31, 20, tzinfo=timezone.utc), is_verified=False))
    session.flush()
    sales.build(session, "s2", CUTOFF)
    assert sales.read(session, "s2", month="2026-02", product_type="timezone")["metrics"]["total_sales_order_count"] == 1
    assert sales.read(session, "s2", month="2026-01", product_type="timezone")["metrics"]["total_sales_order_count"] == 0
    session.execute(delete(runs).where(runs.c.id == "s2"))
    assert session.scalar(select(func.count()).select_from(sales.coupons).where(sales.coupons.c.publication_id == "s2")) == 0
    assert session.scalar(select(func.count()).select_from(SettlementOrderDetail)) == 9


@pytest.mark.skipif(os.getenv("DYDATA_PUBLICATION_RUN_SCALE_BENCHMARK") != "1", reason="opt-in synthetic scale benchmark")
def test_publication_scale_benchmark(publication_postgres_session):
    """Reproduce local timings without source data, cached results or warm-up reads.

    Run with DYDATA_PUBLICATION_TEST_DATABASE_URL and
    DYDATA_PUBLICATION_RUN_SCALE_BENCHMARK=1, pytest -s -k scale_benchmark.
    All data belongs to the disposable schema supplied by the fixture.
    """
    session = publication_postgres_session
    sales.metadata.create_all(session.get_bind())
    session.execute(runs.insert(), [{"id": module, "module": module, "status": "building", "cutoff": CUTOFF,
                                     "created_at": CUTOFF} for module in ("sales", "clues")])
    session.execute(text("""
        INSERT INTO dashboard_publication_sales_coupons
            (publication_id,coupon_id,order_id,product_type,sale_store_id,sale_time,sale_month,
             is_verified,verify_store_id,verify_time,verify_month,paid_amount_cent,cycle_days)
        SELECT 'sales','coupon-'||coupon,'order-'||order_number,'product-'||((order_number/200)%5),
               'store-'||(order_number%200),sale_at,to_char(sale_at AT TIME ZONE 'Asia/Shanghai','YYYY-MM'),
               true,'store-'||((order_number + CASE WHEN coupon%7=0 THEN 1 ELSE 0 END)%200),
               sale_at+duration*interval '1 day',
               to_char((sale_at+duration*interval '1 day') AT TIME ZONE 'Asia/Shanghai','YYYY-MM'),
               10000,duration
        FROM (
            SELECT coupon,(coupon-1)/2 AS order_number,
                   timestamptz '2026-01-01 00:00:00+08'+((coupon-1)/2%365)*interval '1 day' AS sale_at,
                   (((coupon-1)/2)%45)+(coupon%2)*0.5 AS duration
            FROM generate_series(1,200000) AS coupon
        ) source
    """))
    session.execute(text("""INSERT INTO dashboard_publication_sales_stores
        SELECT 'sales','store-'||number,'Synthetic Store '||number FROM generate_series(0,199) number"""))
    session.execute(text("""
        INSERT INTO dashboard_publication_clue_rounds
            (publication_id,assignment_round_id,order_id,assigned_at,assigned_store_id,
             assigned_store_name,order_assigned_store_name,assigned_province,assigned_city,
             product_type,is_jingcheng,is_headquarters,lead_status,round_status,store_display_status,
             verified_at,is_self_store_verified,active_clue,followed_clue,successful_follow_clue,
             self_store_verified_clue,pending_reassign_clue)
        SELECT 'clues','round-'||number,'order-'||((number-1)/2),
               timestamptz '2026-09-01 00:00:00+08'+((number-1)/2%365)*interval '1 day',
               'store-'||(number%200),'Synthetic Store '||(number%200),'Synthetic Store '||(number%200),
               'Province-'||(number%10),'City-'||(number%40),'product-'||((number/200)%5),
               number%2=0,false,'active','active_followed','已跟进',NULL,false,
               CASE WHEN number%2=0 THEN 1 ELSE 0 END,1,
               CASE WHEN number%3=0 THEN 1 ELSE 0 END,0,0
        FROM generate_series(1,100000) number
    """))
    for table in (sales.coupons, sales.stores, clues.rounds):
        session.execute(text(f"ANALYZE {table.name}"))
    session.commit()
    assert session.scalar(select(func.count()).select_from(sales.coupons)) == 200000
    assert session.scalar(select(func.count(func.distinct(sales.coupons.c.order_id)))) == 100000
    assert session.scalar(select(func.count()).select_from(clues.rounds)) == 100000
    checks = [
        ("sales_year", lambda: sales.read(session, "sales", month="all", year=2026)),
        ("sales_history", lambda: sales.read(session, "sales", month="history")),
        ("sales_month", lambda: sales.read(session, "sales", month="2026-06", year=2026)),
        ("sales_store", lambda: sales.read(session, "sales", store_id="store-42", month="all", year=2026)),
        ("clues_global", lambda: clues.read(session, "clues", {})),
        ("clues_group_scope", lambda: clues.read(session, "clues", {"scope_store_ids": [f"store-{index}" for index in range(20)]},
                                                  current_headquarters_order_ids=[])),
    ]
    results = []
    for name, operation in checks:
        for iteration in range(int(os.getenv("DYDATA_PUBLICATION_BENCHMARK_REPETITIONS", "3"))):
            statements = []
            def begin_capture(connection, cursor, statement, parameters, context, executemany):
                context.publication_benchmark_start = perf_counter()
            def capture(connection, cursor, statement, parameters, context, executemany):
                statements.append({"rows": cursor.rowcount, "sql": statement,
                                   "seconds": round(perf_counter() - context.publication_benchmark_start, 4)})
            event.listen(session.get_bind(), "before_cursor_execute", begin_capture)
            event.listen(session.get_bind(), "after_cursor_execute", capture)
            try:
                start = perf_counter()
                result = operation()
                elapsed = perf_counter() - start
            finally:
                event.remove(session.get_bind(), "before_cursor_execute", begin_capture)
                event.remove(session.get_bind(), "after_cursor_execute", capture)
            max_rows = max(statement["rows"] for statement in statements)
            assert max_rows <= 500, "read must never materialize coupon/round fact lists"
            assert all(statement["sql"].lstrip().upper().startswith(("SELECT", "WITH")) for statement in statements)
            results.append({"case": name, "iteration": iteration+1, "seconds": round(elapsed, 4),
                            "sql_count": len(statements), "max_statement_rows": max_rows,
                            "total_statement_rows": sum(max(statement["rows"], 0) for statement in statements),
                            "statement_seconds": [statement["seconds"] for statement in statements]})
            assert result
            if name.startswith("sales_"):
                assert len(result["cycle_rows"]) == 5
                assert all(len(row["sample_points"]) == 90 for row in result["cycle_rows"])
    print("PUBLICATION_SCALE_BENCHMARK=" + json.dumps({"coupons": 200000, "distinct_orders": 100000,
          "months": 12, "products": 5, "stores": 200, "clue_rounds": 100000, "runs": results}, ensure_ascii=False))
