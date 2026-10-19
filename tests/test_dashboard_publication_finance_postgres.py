"""Real PostgreSQL finance projection gate in a disposable dedicated schema."""

from __future__ import annotations

import os
import re
import json
from time import perf_counter
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, func, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from test_dashboard_publication_finance import (
    _run, _seed_finance, publication,
    test_failed_build_rolls_back_owned_projection_rows as _assert_failed_build_rollback,
    test_finance_parity_scope_filters_export_and_frozen_source as _assert_finance_parity,
    test_settlement_parity_huge_integer_cent_scope_and_no_legacy_drift as _assert_settlement_parity,
    test_monthly_frozen_lines_match_multicoupon_refund_and_locked_facts as _assert_monthly_lines,
    test_selector_months_follow_cutoff_without_empty_current_month as _assert_selector_months,
    test_selector_keeps_real_current_month_period as _assert_current_month_period,
    test_finance_retired_statement_allocation_keeps_period_totals_and_filter_parity as _assert_retired_allocation,
)
from dy_api.dashboard_publications.schema import metadata, runs
from dy_api.db import normalize_database_url
from dy_api.models import (
    AggStoreMonthlySettlement, AggStoreRanking, Base, DimStore, PromotionInvoice,
    SettlementProjectionActive, SettlementProjectionGeneration, SettlementStatement,
    SettlementStatementLine,
)


PUBLICATION_POSTGRES_URL = os.getenv("DYDATA_PUBLICATION_TEST_DATABASE_URL")
POSTGRES_URL = PUBLICATION_POSTGRES_URL or os.getenv("DYDATA_T12_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")
SCHEMA_PATTERN = re.compile(r"pub_finance_[0-9a-f]{12}\Z")


@pytest.fixture()
def postgres_session():
    url = make_url(normalize_database_url(POSTGRES_URL))
    assert url.drivername.startswith("postgresql+")
    assert url.host in {"127.0.0.1", "localhost"}
    if PUBLICATION_POSTGRES_URL:
        assert "test" in (url.database or "").lower()
    else:
        assert url.port == 15432 and url.database == url.username == "dydata_t12"
    schema = f"pub_finance_{uuid4().hex[:12]}"
    assert SCHEMA_PATTERN.fullmatch(schema)
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options":
        f"-c search_path={schema} -c lock_timeout=5000 -c statement_timeout=120000"})
    try:
        Base.metadata.create_all(engine)
        metadata.create_all(engine)
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            yield session
    finally:
        engine.dispose()
        assert SCHEMA_PATTERN.fullmatch(schema)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
def test_postgres_finance_parity(postgres_session, direction, monkeypatch):
    _assert_finance_parity(postgres_session, direction, monkeypatch)


@pytest.mark.parametrize("invoice_status,allocation_current,invoice_current,tombstone", [
    (2, True, True, False), (3, True, True, False),
    (3, False, True, False), (3, True, False, False),
    (3, True, True, True), (4, True, True, False),
])
def test_postgres_retired_statement_allocation(
    postgres_session, invoice_status, allocation_current, invoice_current, tombstone,
):
    _assert_retired_allocation(postgres_session, invoice_status, allocation_current,
        invoice_current, tombstone)


@pytest.mark.parametrize("legacy_root", [False, True])
def test_postgres_settlement_parity(postgres_session, legacy_root):
    _assert_settlement_parity(postgres_session, legacy_root)


def test_postgres_failed_build_rollback(postgres_session, monkeypatch):
    _assert_failed_build_rollback(postgres_session, monkeypatch)


def test_postgres_delete_cascades_only_analysis(postgres_session):
    _seed_finance(postgres_session)
    _run(postgres_session, "finance-v1", "finance")
    publication.build_finance(postgres_session, "finance-v1", datetime(2026, 10, 19, tzinfo=UTC))
    postgres_session.commit()
    postgres_session.execute(delete(runs).where(runs.c.id == "finance-v1"))
    postgres_session.commit()
    for table in (publication.statements, publication.invoices, publication.pending,
                  publication.pending_members, publication.dimensions):
        assert postgres_session.scalar(select(func.count()).select_from(table)) == 0
    assert postgres_session.scalar(select(func.count()).select_from(SettlementStatement)) == 5
    assert postgres_session.scalar(select(func.count()).select_from(PromotionInvoice)) == 1


@pytest.mark.parametrize("locked", [False, True])
def test_postgres_multicoupon_adjustment_lines(postgres_session, locked):
    _assert_monthly_lines(postgres_session, locked)


@pytest.mark.parametrize("module", ["settlement", "finance"])
def test_postgres_selector_month_boundary(postgres_session, module):
    _assert_selector_months(postgres_session, module)


@pytest.mark.parametrize("module", ["settlement", "finance"])
@pytest.mark.parametrize("source_kind", ["projection", "statement"])
def test_postgres_real_current_month_period(postgres_session, module, source_kind):
    _assert_current_month_period(postgres_session, module, source_kind)


def _peak_memory_mib():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class MemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD),
                *((key, ctypes.c_size_t) for key in (
                    "peak_working_set", "working_set", "peak_paged", "paged",
                    "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile"))]

        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
            ctypes.POINTER(MemoryCounters), wintypes.DWORD]
        process = ctypes.windll.kernel32.GetCurrentProcess()
        assert ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        return counters.peak_working_set / (1024 * 1024)
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def test_postgres_200_stores_12_months_build_budget(postgres_session):
    session = postgres_session
    months = [f"2026-{month:02d}" for month in range(1, 13)]
    session.execute(insert(DimStore), [{"store_id": f"scale-{index:03d}",
        "store_name": f"Scale {index:03d}"} for index in range(200)])
    session.add(SettlementProjectionGeneration(generation_id="scale-root", state="published",
        generation_kind="legacy_root", input_fingerprint="scale-root"))
    session.flush()
    session.add(SettlementProjectionActive(projection_name="settlement", generation_id="scale-root"))
    aggregates, ranks, formal, lines = [], [], [], []
    for month in months:
        for index in range(200):
            values = dict(month=month, store_id=f"scale-{index:03d}",
                product_scope="all", product_type="all", sales_order_count=10,
                sales_amount_cent=1234567, verified_order_count=5, verified_amount_cent=345678,
                promotion_net_fee_cent=17001, management_net_fee_cent=7003, projection_run_id="scale")
            aggregates.append(values)
            for period in (1, 2):
                ranks.append({**values, "period_type": period, "period_key": month,
                    "store_name": f"Scale {index:03d}", "net_settlement_reference_cent": 9998,
                    "projection_run_id": "scale"})
            if index % 25 == 0:
                statement_id = f"scale-{index}-{month}"
                formal.append(dict(statement_id=statement_id, store_id=values["store_id"],
                    statement_month=month, statement_status=4, promotion_original_fee_cent=17001,
                    promotion_net_fee_cent=17001, management_original_fee_cent=7003,
                    management_net_fee_cent=7003))
                for direction, amount in ((1, 17001), (2, 7003)):
                    lines.append(dict(statement_line_id=f"line-{statement_id}-{direction}",
                        statement_id=statement_id, fee_direction=direction,
                        product_scope="all", product_type="all", original_fee_cent=amount, net_fee_cent=amount))
    session.execute(insert(AggStoreMonthlySettlement), aggregates)
    session.execute(insert(AggStoreRanking), ranks)
    session.execute(insert(SettlementStatement), formal)
    session.execute(insert(SettlementStatementLine), lines)
    session.commit()
    _run(session, "scale-publication", "settlement")
    count = 0

    def observe(*args):
        nonlocal count
        count += 1

    event.listen(session.get_bind(), "before_cursor_execute", observe)
    started = perf_counter()
    try:
        stats = publication.build_settlement(session, "scale-publication", datetime(2026, 12, 31, tzinfo=UTC))
        session.commit()
        build_seconds, build_sql = perf_counter() - started, count
        count = 0
        started = perf_counter()
        result = publication.read_store_ranking(session, "scale-publication", dict(
            period_type="CUMULATIVE", period_key="2026-12", page=1, page_size=20,
            scope_store_ids=("scale-001", "scale-002")))
        monthly_result = publication.read_monthly_settlement(session, "scale-publication", dict(
            store_id="scale-001", month="2026-12", scope_store_ids=("scale-001",)))
        read_seconds, read_sql = perf_counter() - started, count
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", observe)
    _run(session, "scale-finance", "finance")
    count = 0
    event.listen(session.get_bind(), "before_cursor_execute", observe)
    started = perf_counter()
    try:
        finance_stats = publication.build_finance(session, "scale-finance", datetime(2026, 12, 31, tzinfo=UTC))
        session.commit()
        finance_build_seconds, finance_build_sql = perf_counter() - started, count
        count = 0
        started = perf_counter()
        finance_filters = dict(month="2026-12", fee_direction="PROMOTION", metric_scope="MONTH",
            scope_store_ids=("scale-001", "scale-002"))
        finance_summary = publication.read_finance_summary(session, "scale-finance", **finance_filters)
        finance_list = publication.read_finance_invoices(session, "scale-finance", **finance_filters)
        finance_read_seconds, finance_read_sql = perf_counter() - started, count
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", observe)
    peak_mib = _peak_memory_mib()
    evidence = dict(stores=200, months=12, aggregate_rows=2400,
        locked_statements=len(formal), locked_lines=len(lines),
        build_seconds=round(build_seconds, 3), build_sql=build_sql,
        read_seconds=round(read_seconds, 3), read_sql=read_sql,
        peak_process_mib=round(peak_mib, 1), publication_rows=stats["row_count"],
        finance_build_seconds=round(finance_build_seconds, 3), finance_build_sql=finance_build_sql,
        finance_read_seconds=round(finance_read_seconds, 3), finance_read_sql=finance_read_sql,
        finance_rows=finance_stats["row_count"])
    print("finance-publication-performance " + json.dumps(evidence, sort_keys=True))
    assert result["total"] == 2 and monthly_result["metrics"]["sales_order_count"] == 10
    assert build_seconds < 180 and read_seconds < 1 and build_sql < 1000
    assert finance_list["total"] == 2 and finance_summary["metrics"]["statement_total_cent"] == 34002
    assert finance_build_seconds < 180 and finance_read_seconds < 1 and finance_build_sql < 1000
    assert peak_mib < 768
