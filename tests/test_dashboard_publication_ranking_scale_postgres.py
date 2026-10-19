"""Opt-in real-source ranking build benchmark in a disposable local PG schema.

Run with DYDATA_PUBLICATION_RANKING_SCALE=1 and the existing local publication
test database URL. The child process has the worker's unchanged 180s budget;
no frozen facts are seeded. Source setup is outside the measured build window.
Python allocation tracing is a separate diagnostic opt-in via
DYDATA_PUBLICATION_RANKING_TRACE=1 because it can exceed the normal runtime.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from time import perf_counter, process_time
import tracemalloc
from uuid import uuid4

import pytest
from sqlalchemy import Integer, String, case, cast, column, create_engine, event, func, insert, literal, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.dy_api.dashboard_publications import ranking, ranking_schema as frozen
from apps.api.dy_api.dashboard_publications.schema import metadata, runs
from apps.api.dy_api.models import (
    Base, ClueAssignmentRound, ClueCenterOrder, ClueFollowUpRecord, ClueMasterLead,
    DimAwemeAccount, DimSkuProductRule, DimStore, DimStorePoiMapping,
    RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord,
)
from apps.api.dy_api.ranking_schema_v1 import metadata as source_metadata, org_history, eligibility
from apps.api.dy_api.ranking_identity import OrderAttributionIndex

ORDER_COUNT, ROUND_COUNT, CENTER_COUNT, STORE_COUNT = 510467, 84944, 85674, 1531
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 10, 19, tzinfo=timezone.utc)


def _peak_rss_bytes():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD),
                *((name, ctypes.c_size_t) for name in ("peak", "current", "peak_paged", "paged",
                    "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile"))]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        assert ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(counters), counters.cb)
        return counters.peak
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def _source_rows(session, model, columns, expressions, count, *, predicate=None):
    numbers = func.generate_series(0, count - 1).table_valued(column("number", Integer)).render_derived(name="numbers")
    number = numbers.c.number
    query = select(*expressions(number)).select_from(numbers)
    if predicate is not None:
        query = query.where(predicate(number))
    session.execute(insert(model).from_select(columns, query))


def _seed_sources(session):
    store = lambda number: literal("S") + cast(number % STORE_COUNT, String)
    order = lambda number: literal("O") + cast(number, String)
    at = lambda number: literal(START) + (number % 291) * text("interval '1 day'")
    _source_rows(session, DimStore, ["store_id", "store_name", "service_store_code"],
        lambda number: [store(number), store(number), store(number)], STORE_COUNT)
    _source_rows(session, DimAwemeAccount, ["account_id", "store_id", "binding_status"],
        lambda number: [literal("account-") + cast(number, String), store(number), literal("active")], STORE_COUNT)
    _source_rows(session, DimStorePoiMapping, ["poi_id", "store_id"],
        lambda number: [literal("poi-") + cast(number, String), store(number)], STORE_COUNT)
    session.add_all([DimSkuProductRule(sku_id="JC", product_id="JC", product_scope="精诚养车"),
        DimSkuProductRule(sku_id="OTHER", product_scope="其他")])
    session.flush()
    session.execute(org_history.insert(), [dict(mapping_version="v1", store_id="S" + str(number),
        service_store_code="S" + str(number), store_name="Store " + str(number), effective_from=START,
        group_key="G" + str(number % 10), group_name="Group " + str(number % 10),
        service_center_key="C" + str(number % 20), service_center_name="Center " + str(number % 20),
        district_key="D" + str(number % 40), district_name="District " + str(number % 40),
        area_key="A" + str(number % 80), area_name="Area " + str(number % 80), source_hash="synthetic-scale")
        for number in range(STORE_COUNT)])
    session.execute(eligibility.insert(), [dict(eligibility_version="e1", service_store_code="S" + str(number),
        effective_from=START, product_scope="精诚养车", source_hash="synthetic-scale") for number in range(STORE_COUNT)])
    _source_rows(session, RawDouyinOrder, ["order_id", "sku_id", "sale_time", "owner_account_id"],
        lambda number: [order(number), case((number % 7 == 0, "OTHER"), else_="JC"), at(number),
            literal("account-") + cast(number % STORE_COUNT, String)], ORDER_COUNT)
    _source_rows(session, ClueMasterLead, ["lead_key", "source_clue_row_key", "source_identity_key", "order_id"],
        lambda number: [literal("L") + cast(number, String), literal("raw-") + cast(number, String),
            literal("identity-") + cast(number, String), order(number)], ROUND_COUNT // 2,
        predicate=lambda number: number % 2 == 0)
    _source_rows(session, ClueCenterOrder, ["order_id", "product_id", "lead_status", "current_round_status"],
        lambda number: [order(number), literal("JC"), literal("active"), literal("active_unfollowed")], CENTER_COUNT)
    _source_rows(session, ClueAssignmentRound,
        ["assignment_round_id", "order_id", "lead_key", "round_no", "assigned_store_id", "assigned_at", "execution_mode", "round_status"],
        lambda number: [literal("R") + func.lpad(cast(number, String), 8, "0"), order(number // 2),
            case(((number // 2) % 2 == 0, literal("L") + cast(number // 2, String))), number % 2 + 1,
            store(number // 2), at(number // 2) + (number % 2) * text("interval '2 hours'"), literal("formal"), literal("active")], ROUND_COUNT)
    _source_rows(session, ClueFollowUpRecord,
        ["follow_up_record_id", "order_id", "assignment_round_id", "assigned_store_id", "round_no", "follow_result", "created_at"],
        lambda number: [literal("F") + cast(number, String), order(number // 2),
            literal("R") + func.lpad(cast(number, String), 8, "0"), store(number // 2), number % 2 + 1,
            literal("appointment"), at(number // 2) + text("interval '4 hours'")], ROUND_COUNT,
        predicate=lambda number: number % 17 == 0)
    _source_rows(session, RawDouyinOrderCoupon, ["coupon_id", "order_id", "raw_order_id"],
        lambda number: [literal("coupon-") + cast(number, String), order(number), number + 1], 1000)
    _source_rows(session, RawDouyinVerifyRecord, ["verify_id", "coupon_id", "poi_id", "verify_status", "verify_time"],
        lambda number: [literal("verify-") + cast(number, String), literal("coupon-") + cast(number, String),
            literal("poi-") + cast(number % STORE_COUNT, String), literal("success"), at(number) + text("interval '12 hours'")], 1000)
    session.commit()
    for model in (RawDouyinOrder, ClueAssignmentRound, ClueCenterOrder, ClueMasterLead,
        ClueFollowUpRecord, RawDouyinOrderCoupon, RawDouyinVerifyRecord):
        session.execute(text("ANALYZE " + model.__tablename__))
    session.commit()


def _measure(schema, trace_memory):
    engine = create_engine(os.environ["DYDATA_PUBLICATION_TEST_DATABASE_URL"], connect_args={"options": f"-csearch_path={schema}"})
    statements, slowest, sql_seconds, first_round_start = 0, [], 0.0, None
    attribution_calls, attribution_seconds = 0, 0.0
    original_resolve = OrderAttributionIndex.resolve

    def measured_resolve(index, **arguments):
        nonlocal attribution_calls, attribution_seconds
        attribution_started = perf_counter()
        try:
            return original_resolve(index, **arguments)
        finally:
            attribution_calls += 1
            attribution_seconds += perf_counter() - attribution_started

    def before(connection, cursor, statement, parameters, context, executemany):
        nonlocal first_round_start
        context.ranking_started = perf_counter()
        if first_round_start is None and statement.startswith("SELECT clue_assignment_rounds."):
            first_round_start = context.ranking_started

    def after(connection, cursor, statement, parameters, context, executemany):
        nonlocal statements, sql_seconds
        statements += 1
        seconds = perf_counter() - context.ranking_started
        sql_seconds += seconds
        slowest.append((seconds, statement[:140].replace("\n", " ")))
        slowest.sort(reverse=True)
        del slowest[5:]

    with Session(engine) as session:
        session.execute(text("SET statement_timeout = '120s'"))
        session.execute(text("SET work_mem = '16MB'"))
        session.execute(runs.insert().values(id="scale", module="douyin-ranking", status="building",
            cutoff=CUTOFF, created_at=CUTOFF, stats_json={}))
        session.commit()
        event.listen(engine, "before_cursor_execute", before)
        event.listen(engine, "after_cursor_execute", after)
        if trace_memory:
            tracemalloc.start(1)
        started = perf_counter()
        cpu_started = process_time()
        OrderAttributionIndex.resolve = measured_resolve
        try:
            stats = ranking.build(session, "scale", CUTOFF)
        finally:
            OrderAttributionIndex.resolve = original_resolve
        session.commit()
        elapsed = perf_counter() - started
        cpu_seconds = process_time() - cpu_started
        python_peak = tracemalloc.get_traced_memory()[1] if trace_memory else None
        if trace_memory:
            tracemalloc.stop()
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
        rss = _peak_rss_bytes()
        print("RANKING_BUILD_ONLY=" + json.dumps(dict(build_seconds=elapsed, cpu_seconds=cpu_seconds,
            rss_peak_bytes=rss, python_peak_bytes=python_peak, build_sql=statements, sql_seconds=sql_seconds,
            attribution_calls=attribution_calls, attribution_seconds=attribution_seconds,
            order_phase_seconds=first_round_start - started if first_round_start else None,
            round_phase_seconds=started + elapsed - first_round_start if first_round_start else None,
            slowest_sql=slowest)), flush=True)
        sizes = [dict(row) for row in session.execute(text("""
            SELECT relname,pg_relation_size(c.oid) AS table_bytes,pg_indexes_size(c.oid) AS index_bytes,
                   pg_total_relation_size(c.oid) AS total_bytes
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=:schema AND c.relkind='r' AND c.relname LIKE 'dashboard_ranking_%'
            ORDER BY c.relname
        """), {"schema": schema}).mappings()]
        # API reads use their connection's normal setting, rather than inherit
        # the builder's worker-local 16MB work_mem budget.
        session.execute(text("RESET work_mem"))
        read_work_mem = session.scalar(text("SHOW work_mem"))
        filter_reads = []
        for name, scope in (("global", None), ("single_store", ("S42",))):
            for iteration in range(3):
                filter_started = perf_counter()
                choices = ranking.read_filters(session, "scale", scope_store_ids=scope)
                measurement = dict(case=name, iteration=iteration + 1, seconds=perf_counter() - filter_started,
                    stores=len(choices["stores"]), months=len(choices["sale_months"]))
                filter_reads.append(measurement)
                print("RANKING_FILTER_READ=" + json.dumps(measurement), flush=True)
        reads = []
        for name, filters in (("group_year", {"level": "group"}),
            ("store_date_range", {"level": "store", "store_id": "S42", "period_start": datetime(2026, 9, 1, tzinfo=timezone.utc)}),
            ("group_filter", {"level": "store", "group_name": "Group 2"})):
            for iteration in range(3):
                options = dict(period_start=START, period_end=CUTOFF, product_scope="all")
                options.update(filters)
                read_started = perf_counter()
                read_rows = []

                def read_capture(connection, cursor, statement, parameters, context, executemany):
                    assert statement.lstrip().upper().startswith(("SELECT", "WITH"))
                    assert "raw_douyin" not in statement and "clue_assignment_rounds" not in statement
                    read_rows.append(cursor.rowcount)

                event.listen(engine, "after_cursor_execute", read_capture)
                try:
                    result = ranking.read_report(session, "scale", **options)
                finally:
                    event.remove(engine, "after_cursor_execute", read_capture)
                measurement = dict(case=name, iteration=iteration + 1, seconds=perf_counter() - read_started,
                    total=result["total"], orders=int(result["totals"]["order_count"]),
                    sql_count=len(read_rows), max_statement_rows=max(read_rows))
                reads.append(measurement)
                print("RANKING_REPORT_READ=" + json.dumps(measurement), flush=True)
                if name == "group_year":
                    assert result["totals"]["order_count"] == ORDER_COUNT
        page_reads = [dict(case=row["case"], iteration=row["iteration"],
            filter_seconds=filter_reads[row["iteration"] - 1]["seconds"], report_seconds=row["seconds"],
            seconds=filter_reads[row["iteration"] - 1]["seconds"] + row["seconds"])
            for row in reads]
        print("RANKING_BUILD_SCALE=" + json.dumps(dict(orders=stats["orders"], rounds=stats["rounds"],
            stores=STORE_COUNT, center_orders=CENTER_COUNT, build_seconds=elapsed, cpu_seconds=cpu_seconds,
            python_cpu_limit="unrestricted local process; not a 0.5-CPU container result",
            read_work_mem=read_work_mem,
            build_sql=statements, rss_peak_bytes=rss,
            attribution_calls=attribution_calls, attribution_seconds=attribution_seconds,
            tracemalloc_enabled=trace_memory, python_peak_bytes=python_peak,
            order_phase_seconds=first_round_start - started if first_round_start else None,
            round_phase_seconds=(started + elapsed - first_round_start) if first_round_start else None,
            sql_seconds=sql_seconds, tables=sizes,
            total_projection_bytes=sum(row["total_bytes"] for row in sizes if row["relname"] != "dashboard_ranking_lead_bindings"),
            persistent_binding_bytes=sum(row["total_bytes"] for row in sizes if row["relname"] == "dashboard_ranking_lead_bindings"),
            slowest_sql=slowest, filter_reads=filter_reads, reads=reads, page_reads=page_reads)), flush=True)
    engine.dispose()


@pytest.mark.parametrize("trace_memory", [False, True], ids=["normal", "python-memory-tracing"])
def test_real_source_build_at_production_scale(tmp_path, trace_memory):
    if os.getenv("DYDATA_PUBLICATION_RANKING_SCALE") != "1":
        pytest.skip("opt in with DYDATA_PUBLICATION_RANKING_SCALE=1 for a full real-source build")
    if trace_memory and os.getenv("DYDATA_PUBLICATION_RANKING_TRACE") != "1":
        pytest.skip("separate allocation diagnostic: set DYDATA_PUBLICATION_RANKING_TRACE=1; instrumentation is not normal worker timing")
    raw = os.environ.get("DYDATA_PUBLICATION_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set local DYDATA_PUBLICATION_TEST_DATABASE_URL")
    url = make_url(raw)
    assert url.host in {"localhost", "127.0.0.1", "::1"} and "test" in (url.database or "").lower()
    schema = "ranking_build_scale_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        source_metadata.create_all(engine)
        metadata.create_all(engine)
        with Session(engine) as session:
            _seed_sources(session)
            for model, expected in ((RawDouyinOrder, ORDER_COUNT), (ClueAssignmentRound, ROUND_COUNT), (ClueCenterOrder, CENTER_COUNT)):
                assert session.scalar(select(func.count()).select_from(model)) == expected
        print(f"Real source fixture ready: {ORDER_COUNT} orders / {ROUND_COUNT} rounds / {CENTER_COUNT} center orders", flush=True)
        output = []
        evidence_path = tmp_path / "ranking-build-scale.jsonl"
        print(f"Immediate UTF-8 evidence: {evidence_path}", flush=True)
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--measure", schema,
                "trace" if trace_memory else "normal"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONUTF8": "1"}, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

        def forward_output():
            with evidence_path.open("w", encoding="utf-8") as evidence:
                for value in process.stdout:
                    output.append(value)
                    evidence.write(value)
                    evidence.flush()
                    print(value, end="", flush=True)

        reader = Thread(target=forward_output, daemon=True)
        reader.start()
        try:
            process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise
        finally:
            reader.join(timeout=5)
            process.stdout.close()
        assert process.returncode == 0, "".join(output)[-6000:]
        line = next(value for value in output if value.startswith("RANKING_BUILD_SCALE="))
        report = json.loads(line.partition("=")[2])
        (tmp_path / "ranking-build-scale.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        assert report["orders"] == ORDER_COUNT and report["rounds"] == ROUND_COUNT
        assert report["build_seconds"] < 180
        assert report["rss_peak_bytes"] < 768 * 1024 * 1024
        assert all(row["seconds"] < 1 for row in report["reads"]), report["reads"]
        assert all(row["seconds"] < 1 for row in report["page_reads"]), report["page_reads"]
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    assert sys.argv[1] == "--measure" and sys.argv[2].startswith("ranking_build_scale_")
    _measure(sys.argv[2], sys.argv[3] == "trace")
