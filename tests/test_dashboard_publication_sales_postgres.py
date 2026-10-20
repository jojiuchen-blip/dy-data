"""Opt-in PostgreSQL checks in a per-test disposable schema."""

import os
import json
import ctypes
import tracemalloc
from ctypes import wintypes
from threading import Event, Thread
from time import perf_counter
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import Index, MetaData, and_, create_engine, delete, event, func, literal_column, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.dashboard_publications import sales
from apps.api.dy_api.dashboard_publications import clues
from apps.api.dy_api.dashboard_publications.schema import runs
from apps.api.dy_api.models import Base, DimStore, SettlementOrderDetail
from test_dashboard_publication_sales import CUTOFF, prepare_sales, assert_sales_parity, assert_cross_product_order_aggregation


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
          "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]]


def _resident_bytes():
    if os.name != "nt":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessMemoryCounters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.WorkingSetSize


def _benchmark_candidate_indexes():
    # A copied Table keeps rejected A/B indexes out of production metadata.
    table = sales.coupons.to_metadata(MetaData())
    return {
        "order": Index("ix_pub_sales_order_product", table.c.publication_id, table.c.order_id.collate("C"),
            table.c.product_type.collate("C"), postgresql_include=["sale_store_id", "sale_month", "is_verified",
                "verify_store_id", "verify_month", "paid_amount_cent", "cycle_days", "cycle_sort_days"]),
        "cycle": Index("ix_pub_sales_cycle_order", table.c.publication_id,
            func.coalesce(func.nullif(table.c.product_type, literal_column("''")), literal_column("'未映射'")).collate("C"),
            table.c.order_id.collate("C"), table.c.cycle_sort_days, postgresql_include=["verify_month", "product_type"],
            postgresql_where=and_(table.c.is_verified.is_(True), table.c.cycle_sort_days.is_not(None))),
    }


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
@pytest.mark.parametrize("index_strategy", os.getenv("DYDATA_PUBLICATION_BENCHMARK_INDEX_STRATEGY", "none").split(","))
def test_publication_scale_benchmark(publication_postgres_session, index_strategy):
    """Reproduce local timings without source data, cached results or warm-up reads.

    Run with DYDATA_PUBLICATION_TEST_DATABASE_URL and
    DYDATA_PUBLICATION_RUN_SCALE_BENCHMARK=1, pytest -s -k scale_benchmark.
    All data belongs to the disposable schema supplied by the fixture.
    """
    session = publication_postgres_session
    sales.metadata.create_all(session.get_bind())
    # These source indexes only slow synthetic fixture preparation. The real
    # builder below performs the same full narrow source scan in every strategy.
    # Keep the primary key; all drops belong to this disposable test schema.
    for index in SettlementOrderDetail.__table__.indexes:
        index.drop(session.connection())
    strategy = index_strategy
    assert strategy in {"none", "cycle", "both"}
    for name, index in _benchmark_candidate_indexes().items():
        if strategy == "both" or (strategy == "cycle" and name == "cycle"):
            index.create(session.connection())
    session.execute(runs.insert(), [{"id": module, "module": module, "status": "building", "cutoff": CUTOFF,
                                     "created_at": CUTOFF} for module in ("sales", "clues")])
    session.execute(text("""
        INSERT INTO settlement_order_details
            (coupon_id,order_id,product_type,sale_store_id,sale_time,is_verified,verify_store_id,verify_time,
             paid_amount_cent,relation_type,is_commissionable,is_refund_excluded,commission_rate,
             receivable_commission_cent,payable_commission_cent,updated_at)
        SELECT 'coupon-'||coupon,'order-'||order_number,'product-'||((order_number/200)%5),
               'store-'||(order_number%200),sale_at,
               true,'store-'||((order_number + CASE WHEN coupon%7=0 THEN 1 ELSE 0 END)%200),
               sale_at+duration*interval '1 day',
               10000,'unknown',false,false,0,0,0,timestamptz '2026-10-19 00:00:00+08'
        FROM (
            SELECT coupon,(coupon-1)/2 AS order_number,
                   timestamptz '2026-01-01 00:00:00+08'+((coupon-1)/2%365)*interval '1 day' AS sale_at,
                   (((coupon-1)/2)%45)+(coupon%2)*0.5 AS duration
            FROM generate_series(1,200000) AS coupon
        ) source
    """))
    session.execute(DimStore.__table__.insert(), [{"store_id": f"store-{number}", "store_name": f"Synthetic Store {number}"} for number in range(200)])
    session.commit()
    initial_rss = _resident_bytes()
    peak_rss = [initial_rss]
    stop_memory_sample = Event()
    def sample_memory():
        while not stop_memory_sample.wait(.02):
            value = _resident_bytes()
            if value is not None:
                peak_rss[0] = max(peak_rss[0] or 0, value)
    memory_thread = Thread(target=sample_memory, daemon=True)
    tracemalloc.start()
    memory_thread.start()
    build_start = perf_counter()
    try:
        sales.build(session, "sales", CUTOFF)
        session.commit()
        build_seconds = perf_counter() - build_start
        python_peak_bytes = tracemalloc.get_traced_memory()[1]
    finally:
        stop_memory_sample.set()
        memory_thread.join()
        tracemalloc.stop()
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
    explain_statements = []
    for name, operation in checks:
        for iteration in range(int(os.getenv("DYDATA_PUBLICATION_BENCHMARK_REPETITIONS", "3"))):
            statements = []
            def begin_capture(connection, cursor, statement, parameters, context, executemany):
                context.publication_benchmark_start = perf_counter()
            def capture(connection, cursor, statement, parameters, context, executemany):
                statements.append({"rows": cursor.rowcount, "sql": statement, "parameters": parameters,
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
            if name == "sales_year" and iteration == 0:
                explain_statements = statements
    relation_bytes = dict(session.execute(text("""SELECT table_class.relname,pg_total_relation_size(table_class.oid)
        FROM pg_class table_class JOIN pg_namespace namespace ON namespace.oid=table_class.relnamespace
        WHERE namespace.nspname=current_schema() AND table_class.relname IN (
          'dashboard_publication_sales_coupons','dashboard_publication_sales_stores',
          'dashboard_publication_sales_product_scopes','dashboard_publication_clue_rounds')""")).all())
    print("PUBLICATION_SCALE_BENCHMARK=" + json.dumps({"coupons": 200000, "distinct_orders": 100000,
          "months": 12, "products": 5, "stores": 200, "clue_rounds": 100000, "index_strategy": strategy,
          "sales_build_seconds": round(build_seconds, 4), "sales_build_python_peak_bytes": python_peak_bytes,
          "sales_build_rss_start_bytes": initial_rss, "sales_build_rss_peak_bytes": peak_rss[0],
          "projection_bytes": relation_bytes, "runs": results}, ensure_ascii=False))
    if os.getenv("DYDATA_PUBLICATION_BENCHMARK_EXPLAIN") == "1":
        def nodes(plan):
            result = [{key: plan[key] for key in ("Node Type", "Index Name", "Actual Total Time", "Actual Rows", "Actual Loops",
                       "Sort Method", "Sort Space Used", "Sort Space Type", "Temp Written Blocks", "HashAgg Batches") if key in plan}]
            for child in plan.get("Plans", []):
                result.extend(nodes(child))
            return result
        reports = []
        for index, statement in enumerate(explain_statements):
            plan = session.connection().exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement["sql"],
                                                       statement["parameters"]).scalar_one()[0]
            reports.append({"statement": index+1, "execution_ms": plan["Execution Time"],
                            "planning_ms": plan["Planning Time"], "jit": plan.get("JIT"), "nodes": nodes(plan["Plan"])})
        print("PUBLICATION_SCALE_EXPLAIN=" + json.dumps(reports, ensure_ascii=False))
        sizes = session.execute(text("""SELECT index_class.relname,pg_relation_size(index_class.oid)
            FROM pg_class index_class JOIN pg_namespace namespace ON namespace.oid=index_class.relnamespace
            WHERE namespace.nspname=current_schema() AND index_class.relname LIKE 'ix_pub_sales%'
            ORDER BY index_class.relname""")).all()
        print("PUBLICATION_SCALE_INDEX_BYTES=" + json.dumps(dict(sizes)))
