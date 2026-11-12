"""Exact-row parity for the reporting-only materialized authority query."""

from unittest.mock import patch

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from apps.api.dy_api.dashboard_publications import commission_types
from apps.api.dy_api.models import (
    DimSkuProductRule, InvoiceRecord, PromotionInvoiceAllocation, SettlementDispute,
    SettlementFeeResult, SettlementStatementConfirmation,
)
from apps.api.dy_api.routes._data import DashboardDataStore
from apps.worker.settlement import _sparse_authority_relation
from test_protected_billing_authority import (
    NOW, _adjustment, _facts, _seed,
    test_exact_frozen_carryforward_keeps_only_active_application_without_losing_other_direction as assert_carryforward,
    test_normal_month_refresh_capture_and_build_use_same_frozen_chain_closure as assert_locked,
    test_reverification_anchor_requires_cancellation_and_explicit_restoration as assert_restoration,
)
from test_protected_billing_authority_postgres import postgres_engine


def _legacy_exact(months):
    expanded = _sparse_authority_relation(tuple(months))
    return select(*(expanded.c[key] for key in expanded.c.keys()
        if key not in {"product_scope", "product_type"})).where(
        expanded.c.product_scope == expanded.c.source_product_scope,
        expanded.c.product_type == expanded.c.source_product_type).subquery("legacy_exact")


def _rows(session, relation):
    keys = sorted(relation.c.keys())
    return sorted((tuple(row) for row in session.execute(select(*(relation.c[key] for key in keys)))), key=repr)


def _reports(session, months):
    return (
        _rows(session, commission_types.authority(months)),
        commission_types.has_changes(session, months),
        commission_types.coverage(session, months),
        sorted((dict(row) for row in commission_types.partitions(session, months)), key=repr),
        {month: commission_types.lines(session, month, DashboardDataStore(session)) for month in months},
    )


def _assert_parity(session):
    # Only the caller's output cohort is month-filtered. September must still
    # suppress primary replacements frozen in August and recover later refunds.
    before = _facts(session)
    for months in ((), ("2026-08",), ("2026-09",), ("2026-08", "2026-09")):
        assert _rows(session, commission_types._exact_authority(months)) == _rows(session, _legacy_exact(months))
        actual = _reports(session, months)
        with patch.object(commission_types, "_exact_authority", _legacy_exact):
            expected = _reports(session, months)
        assert actual == expected
    assert _facts(session) == before


def _catalog(session):
    session.add_all([
        DimSkuProductRule(sku_id="frozen-sku", product_scope="unrelated", product_type="精诚养车"),
        DimSkuProductRule(sku_id="sku-old", product_scope="unrelated", product_type="售后官方"),
    ])
    session.commit()


@pytest.mark.parametrize("protection", (
    "confirmation", "confirmed-at", "locked-at", "status-3", "status-4",
    "dispute", "resolved-dispute", "allocation", "invoice", "unprotected", "retired",
))
def test_exact_and_classified_rows_preserve_every_protection_branch(postgres_engine, protection):
    with Session(postgres_engine, autoflush=False) as session:
        bill = _seed(session)
        if protection != "confirmation":
            session.execute(delete(SettlementStatementConfirmation))
        if protection == "confirmed-at":
            bill.confirmed_at = NOW
        elif protection == "locked-at":
            bill.locked_at = NOW
        elif protection.startswith("status-"):
            bill.statement_status = int(protection[-1])
        elif protection in {"dispute", "resolved-dispute"}:
            session.add(SettlementDispute(dispute_id="synthetic-dispute", statement_id=bill.statement_id,
                store_id=bill.store_id, statement_month=bill.statement_month, fee_direction=2,
                dispute_type=1, status=1 if protection == "dispute" else 6,
                result_statement_id=bill.statement_id if protection == "resolved-dispute" else None,
                description="Synthetic", contact_name="Synthetic", contact_phone_ciphertext="synthetic",
                submitted_by="synthetic", idempotency_key_hash="synthetic"))
        elif protection == "allocation":
            session.add(PromotionInvoiceAllocation(allocation_id="synthetic-allocation", invoice_id="synthetic-invoice",
                store_id=bill.store_id, statement_id=bill.statement_id, statement_month=bill.statement_month,
                settlement_batch_month="2026-09", allocated_amount_cent=800, is_current=False))
        elif protection == "invoice":
            session.add(InvoiceRecord(invoice_id="synthetic-invoice", store_id=bill.store_id,
                statement_id=bill.statement_id, statement_month=bill.statement_month, fee_direction=2,
                version_no=1, is_current=False, is_tombstone=True, invoice_status=4,
                invoice_number="12345678901234567890", invoice_date=NOW.date(),
                invoice_amount_cent=500, source_type=2, registered_by="synthetic"))
        elif protection == "retired":
            bill.is_current = False
            bill.statement_status = 4
        _adjustment(session, "later-refund", "old-promotion")
        _catalog(session)
        _assert_parity(session)


@pytest.mark.parametrize("scenario", ("restoration", "unapproved-replacement", "carryforward", "locked"))
def test_exact_query_preserves_cross_month_events_and_rejection(postgres_engine, monkeypatch, scenario):
    with Session(postgres_engine, autoflush=False) as session:
        if scenario == "carryforward":
            assert_carryforward(session)
        elif scenario == "locked":
            assert_locked(session, monkeypatch, True)
        else:
            assert_restoration(session, scenario == "restoration")
        _catalog(session)
        _assert_parity(session)


def test_multisku_counts_legacy_uncovered_and_unknown_dimensions(postgres_engine, monkeypatch):
    from test_commission_product_publication import test_unresolved_and_uncovered_history_are_counted_and_remain_visible

    with Session(postgres_engine, autoflush=False) as session:
        test_unresolved_and_uncovered_history_are_counted_and_remain_visible(session, monkeypatch)
        # All/empty dimensions collapse in the old UNION. Preserve exact set
        # semantics before reporting re-expansion, including unknown SKU/type.
        result = session.scalar(select(SettlementFeeResult).where(SettlementFeeResult.fee_result_id == "missing-catalog"))
        result.product_scope = "all"
        result.product_type = ""
        result.sku_id = ""
        session.commit()
        _assert_parity(session)


@pytest.mark.parametrize("postgres_engine", ("migration",), indirect=True)
def test_migrated_schema_preserves_frozen_rows_with_unknown_snapshots(postgres_engine):
    with Session(postgres_engine, autoflush=False) as session:
        _seed(session, receipt=None)
        _catalog(session)
        session.execute(text("""
            INSERT INTO settlement_statement_snapshot_migration_exception
                (statement_id, reason_code, evidence_json, detected_at, gmt_create, gmt_modified)
            VALUES ('frozen-bill', 'NO_PRIOR_BASIC_PROFILE', '{}', now(), now(), now())
        """))
        session.execute(text("""
            INSERT INTO settlement_statement_entry_snapshot_migration_exception
                (statement_entry_id, statement_id, reason_code, evidence_json, detected_at, gmt_create, gmt_modified)
            SELECT statement_entry_id, statement_id, 'MISSING_REQUIRED_ENTRY_SNAPSHOT', '{}', now(), now(), now()
            FROM settlement_statement_entry WHERE source_record_id = 'old-promotion'
        """))
        session.commit()
        exceptions = {
            name: session.execute(text(f"SELECT * FROM {name} ORDER BY id")).all()
            for name in ("settlement_statement_snapshot_migration_exception",
                         "settlement_statement_entry_snapshot_migration_exception")
        }
        _assert_parity(session)
        for name, before in exceptions.items():
            assert before and session.execute(text(f"SELECT * FROM {name} ORDER BY id")).all() == before


def test_compiled_query_reuses_protection_and_dimension_source():
    class Capture:
        def execute(self, query):
            self.query = query
            return self

        def mappings(self):
            return []

    capture = Capture()
    for build in (commission_types.coverage, commission_types.partitions):
        build(capture, ("2026-08", "2026-09"))
        sql = str(capture.query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        assert sql.count("AS MATERIALIZED") == 4
        for relation in ("settlement_statement_confirmation", "settlement_dispute", "promotion_invoice_allocation", "invoice_record"):
            assert sql.count("FROM " + relation + " ") == 1
        assert len(sql) < 25000
