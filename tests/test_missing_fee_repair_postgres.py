"""Disposable loopback PostgreSQL: real locks, atomic rollback and replay."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timezone
import os
import json
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.api.dy_api import models as m
from apps.worker import missing_fee_repair as repair
from apps.worker import settlement as s
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY
from test_missing_fee_repair import setup_batch, preview, test_preview_emits_select_only_and_quote_is_frozen as _assert_select_only


@pytest.fixture()
def pg_engine(request, monkeypatch):
    url = os.getenv("DYDATA_MISSING_FEE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set DYDATA_MISSING_FEE_TEST_DATABASE_URL to a disposable loopback *_test database")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database.endswith("_test")
    schema = "missing_fee_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=1000"})
    try:
        if getattr(request, "param", None) == "migration":
            from alembic import command
            from alembic.config import Config
            isolated = parsed.update_query_dict({"options": f"-csearch_path={schema}"})
            monkeypatch.setenv("DY_DATABASE_URL", isolated.render_as_string(hide_password=False))
            root = Path(__file__).resolve().parents[1]
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "alembic"))
            command.upgrade(config, "head")
        else:
            m.Base.metadata.create_all(engine)
            from apps.api.dy_api.dashboard_publications.schema import metadata
            metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        # Schema is a generated identifier, on the verified disposable database.
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def apply(session, manifest, exclusions, expected):
    return repair.apply_missing_fees(session, manifest=manifest, exclusions=exclusions, preview_hash=expected)


def counts(session):
    return tuple(session.scalar(select(func.count()).select_from(model))
                 for model in (m.SettlementFeeResult, m.SettlementFeeResultCurrent,
                               m.SettlementFeeAdjustment, m.FinanceOperationAudit, m.JobRun))


def test_postgres_preview_select_only(pg_engine):
    with Session(pg_engine, autoflush=True) as session:
        _assert_select_only(session)


@pytest.mark.parametrize("pg_engine", ("metadata", "migration"), indirect=True)
def test_postgres_apply_commit_readback_and_exact_idempotence(pg_engine):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session, count=2)
        report = preview(session, manifest, exclusions)
        applied = apply(session, manifest, exclusions, report["preview_hash"])
        assert applied["applied"] and not applied["replayed"]
        assert applied["financial_before"] == applied["financial_after"]
    with Session(pg_engine, autoflush=False) as session:
        assert counts(session) == (4, 4, 0, 1, 0)
        session.rollback()
        replayed = apply(session, manifest, exclusions, report["preview_hash"])
        assert replayed["replayed"]
        assert counts(session) == (4, 4, 0, 1, 0)
        session.rollback()
        altered = deepcopy(exclusions)
        values = ["new-exclusion"]
        altered["groups"]["protected"] = {"coupon_ids": values, "count": 1, "sha256": repair.digest(values)}
        with pytest.raises(repair.MissingFeeRepairError, match="idempotency"):
            apply(session, manifest, altered, report["preview_hash"])
        with pytest.raises(repair.MissingFeeRepairError, match="idempotency"):
            apply(session, manifest, exclusions, "a" * 64)
        row = session.scalar(select(m.SettlementFeeResult).limit(1))
        row.input_fingerprint = "b" * 64
        session.commit()
        with pytest.raises(repair.MissingFeeRepairError, match="outputs changed"):
            apply(session, manifest, exclusions, report["preview_hash"])


@pytest.mark.parametrize("drift", ["rate", "new-rate", "scope", "sku", "store-name", "raw-order", "receipt", "sibling", "binding"])
def test_postgres_full_dependency_drift_rejects_zero_writes(pg_engine, drift):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session)
        report = preview(session, manifest, exclusions)
        if drift == "rate":
            session.scalar(select(m.SkuFeeRule)).promotion_service_fee_rate = "0.300000"
        elif drift == "new-rate":
            from test_receipt_commission_basis import _add_fee_rule
            _add_fee_rule(session, "new-rate", date(2026, 9, 2), promotion="0.4", management="0.3")
        elif drift == "scope":
            session.scalar(select(m.SettlementScopeRule)).change_reason = "changed evidence"
        elif drift == "sku":
            session.scalar(select(m.DimSkuProductRule)).sku_name = "changed name"
        elif drift == "store-name":
            session.get(m.DimStore, "store-verify").store_name = "changed mapped store snapshot"
        elif drift == "raw-order":
            session.get(m.RawDouyinOrder, manifest["coupons"][0]["raw_order_id"]).raw_payload = {"extra_evidence": "new"}
        elif drift == "receipt":
            session.get(m.RawDouyinOrderCoupon, manifest["coupons"][0]["raw_coupon_id"]).raw_payload = {"receipt_amount": 12000}
        elif drift == "sibling":
            entry = manifest["coupons"][0]
            session.add(m.RawDouyinOrderCoupon(coupon_id="unapproved-sibling", order_id=entry["order_id"],
                                               raw_order_id=entry["raw_order_id"], raw_payload={"receipt_amount": 10}))
        elif drift == "binding":
            session.add(m.RawAwemeBinding(binding_key="new-unrelated-config", account_id="unrelated", raw_payload={}))
        session.commit()
        with pytest.raises(repair.MissingFeeRepairError, match="hash changed"):
            apply(session, manifest, exclusions, report["preview_hash"])
        assert counts(session) == (0, 0, 0, 0, 0)


@pytest.mark.parametrize("month,status,pointer", [("2026-09", 1, True), ("2026-08", 2, False), ("2026-08", 3, False)])
def test_postgres_any_historical_direction_status_month_rejects(pg_engine, month, status, pointer):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session)
        report = preview(session, manifest, exclusions)
        s.rebuild_dual_fee_results(session, calculation_run_id="unrelated-history",
                                  coupon_ids=[manifest["coupons"][0]["coupon_id"]])
        if not pointer:
            session.execute(delete(m.SettlementFeeResultCurrent))
        for result in session.scalars(select(m.SettlementFeeResult)):
            result.original_business_month = month
            result.result_status = status
        session.commit()
        with pytest.raises(repair.MissingFeeRepairError, match="history"):
            apply(session, manifest, exclusions, report["preview_hash"])
        assert session.scalar(select(func.count()).select_from(m.FinanceOperationAudit)) == 0


@pytest.mark.parametrize("protection", ["confirmed", "confirmation", "locked", "historical-lock", "invoice", "orphan-dispute"])
def test_postgres_all_target_protection_facts_reject(pg_engine, protection):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session)
        report = preview(session, manifest, exclusions)
        bill = m.SettlementStatement(statement_id="existing-bill", store_id="store-sale", statement_month="2026-09")
        session.add(bill)
        if protection == "confirmed":
            bill.confirmed_at = datetime.now(timezone.utc)
        elif protection == "locked":
            bill.locked_at = datetime.now(timezone.utc)
        elif protection == "historical-lock":
            bill.is_current = False
            bill.statement_status = 4
        elif protection == "confirmation":
            session.add(m.SettlementStatementConfirmation(confirmation_id="existing-confirmation",
                statement_id=bill.statement_id, fee_direction=2, confirmed_by="synthetic-test"))
        elif protection == "invoice":
            session.add(m.InvoiceRecord(invoice_id="existing-invoice", store_id="store-sale", statement_month="2026-09",
                statement_id=bill.statement_id, fee_direction=1, invoice_number="1" * 20,
                invoice_date=date(2026, 10, 1), invoice_amount_cent=1, source_type=1, registered_by="synthetic-test"))
        elif protection == "orphan-dispute":
            session.expunge(bill)
            session.add(m.SettlementDispute(dispute_id="orphan-dispute", statement_id="absent-bill",
                store_id="store-sale", statement_month="2026-09", fee_direction=1, dispute_type=1,
                description="test", contact_name="synthetic-test", contact_phone_ciphertext="synthetic-test", submitted_by="synthetic-test"))
        session.commit()
        with pytest.raises(repair.MissingFeeRepairError, match="protected|history"):
            apply(session, manifest, exclusions, report["preview_hash"])
        assert session.scalar(select(func.count()).select_from(m.SettlementFeeResult)) == 0
        assert session.scalar(select(func.count()).select_from(m.FinanceOperationAudit)) == 0


@pytest.mark.parametrize("failure", ["fields", "adjustment-count", "outside", "budget"])
def test_postgres_unexpected_writer_outputs_roll_back_entire_batch(pg_engine, monkeypatch, failure):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session, count=2)
        report = preview(session, manifest, exclusions)
        original = s.rebuild_dual_fee_results
        def unexpected(session, **kwargs):
            stats = original(session, **kwargs)
            if failure == "fields":
                row = session.scalar(select(m.SettlementFeeResult).limit(1))
                row.qualifying_verify_store_name = "wrong snapshot"
                session.flush()
            elif failure == "adjustment-count":
                return s.DualFeeStats(result_count=4, adjustment_count=1, blocked_count=0)
            elif failure == "outside":
                session.add(m.SettlementStatement(statement_id="unexpected-bill", store_id="unrelated", statement_month="2026-08"))
                session.flush()
            elif failure == "budget":
                raise repair.MissingFeeBudgetError("injected budget exhaustion after first writes")
            return stats
        monkeypatch.setattr(s, "rebuild_dual_fee_results", unexpected)
        with pytest.raises(repair.MissingFeeRepairError):
            apply(session, manifest, exclusions, report["preview_hash"])
        assert counts(session) == (0, 0, 0, 0, 0)
        assert session.scalar(select(func.count()).select_from(m.SettlementStatement)) == 0


@pytest.mark.parametrize("writer_status", ["running", "retry_wait"])
def test_postgres_active_source_writer_rejects(pg_engine, writer_status):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session)
        report = preview(session, manifest, exclusions)
        session.add(m.JobRun(job_id="existing-writer", job_name="settlement_rebuild", status=writer_status))
        session.commit()
        with pytest.raises(repair.MissingFeeRepairError, match="source writer"):
            apply(session, manifest, exclusions, report["preview_hash"])
        assert session.scalar(select(func.count()).select_from(m.SettlementFeeResult)) == 0


def test_postgres_heavy_claim_conflict_rejects(pg_engine):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session)
        report = preview(session, manifest, exclusions)
        with pg_engine.begin() as other:
            assert other.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY)))
            with pytest.raises(repair.MissingFeeRepairError, match="claim lock busy"):
                apply(session, manifest, exclusions, report["preview_hash"])
        assert counts(session) == (0, 0, 0, 0, 0)


@pytest.mark.parametrize("phantom", ["raw", "config", "protection"])
def test_postgres_relation_fences_block_insert_phantoms(pg_engine, monkeypatch, phantom):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session)
        report = preview(session, manifest, exclusions)
        real_preview = repair._preview
        def try_phantom():
            with pg_engine.connect() as conn:
                conn.execute(text("SET LOCAL lock_timeout = '200ms'"))
                try:
                    if phantom == "raw":
                        conn.execute(m.RawDouyinVerifyRecord.__table__.insert().values(
                            verify_id="phantom-verify", coupon_id=manifest["coupons"][0]["coupon_id"],
                            verify_status="valid", raw_payload={}))
                    elif phantom == "config":
                        conn.execute(m.DimStorePoiMapping.__table__.insert().values(
                            store_id="store-verify", poi_id="phantom-poi", mapping_source="synthetic-test"))
                    elif phantom == "protection":
                        conn.execute(m.SettlementStatementConfirmation.__table__.insert().values(
                            confirmation_id="phantom-confirmation", statement_id="absent-bill", fee_direction=1,
                            confirmed_by="synthetic-test"))
                except DBAPIError as exc:
                    assert getattr(exc.orig, "sqlstate", getattr(exc.orig, "pgcode", None)) == "55P03"
                    return True
                finally:
                    conn.rollback()
            return False
        def assert_fenced(*args, **kwargs):
            with ThreadPoolExecutor(max_workers=1) as executor:
                assert executor.submit(try_phantom).result(timeout=5)
            return real_preview(*args, **kwargs)
        monkeypatch.setattr(repair, "_preview", assert_fenced)
        apply(session, manifest, exclusions, report["preview_hash"])
        assert counts(session) == (2, 2, 0, 1, 0)


def test_postgres_existing_source_transaction_times_out_without_writes(pg_engine):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session)
        report = preview(session, manifest, exclusions)
        with pg_engine.connect() as other:
            other.execute(text("UPDATE dim_sku_product_rules SET sku_name='uncommitted-source-change'"))
            with pytest.raises(DBAPIError) as error:
                apply(session, manifest, exclusions, report["preview_hash"])
            assert getattr(error.value.orig, "sqlstate", getattr(error.value.orig, "pgcode", None)) == "55P03"
            other.rollback()
        assert counts(session) == (0, 0, 0, 0, 0)


def test_postgres_transaction_characteristics_and_fixed_timeouts(pg_engine, monkeypatch):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session)
        original = repair._preview
        seen = []
        def observe(session, *args):
            seen.append(session.execute(text("SELECT current_setting('transaction_isolation'), "
                "current_setting('transaction_read_only'), current_setting('lock_timeout'), "
                "current_setting('statement_timeout')")).one())
            return original(session, *args)
        monkeypatch.setattr(repair, "_preview", observe)
        report = preview(session, manifest, exclusions)
        assert seen[-1][:2] == ("repeatable read", "on")
        apply(session, manifest, exclusions, report["preview_hash"])
        assert seen[-1] == ("read committed", "off", "1s", "5s")


@pytest.mark.parametrize("coupon_count", (10, 20, 50, 373))
def test_postgres_reviewed_batch_representative_budget_receipt(pg_engine, tmp_path, monkeypatch, coupon_count):
    """Measure the real guarded path, recording refusal instead of raising budgets."""
    from test_receipt_commission_basis import _seed_dual_base
    with Session(pg_engine, autoflush=False) as session:
        _seed_dual_base(session)
        session.flush()
        at = datetime(2026, 9, 5, 2, tzinfo=timezone.utc)
        orders = [dict(order_id=f"perf-order-{index}", order_status_normalized="paid", sku_id="sku-dual",
                       sale_time=at, pay_time=at, owner_account_id="owner-dual", owner_account_name="Owner Dual",
                       sale_channel_normalized="short_video", raw_payload={}) for index in range(coupon_count)]
        session.execute(m.RawDouyinOrder.__table__.insert(), orders)
        order_rows = list(session.execute(select(m.RawDouyinOrder.id, m.RawDouyinOrder.order_id).order_by(m.RawDouyinOrder.order_id)))
        coupons = [dict(coupon_id=f"perf-coupon-{index}", order_id=row.order_id, raw_order_id=row.id,
                        coupon_status_normalized="available", raw_payload={"receipt_amount": 10000})
                   for index, row in enumerate(order_rows)]
        session.execute(m.RawDouyinOrderCoupon.__table__.insert(), coupons)
        coupon_rows = list(session.scalars(select(m.RawDouyinOrderCoupon).order_by(m.RawDouyinOrderCoupon.coupon_id)))
        session.execute(m.RawDouyinVerifyRecord.__table__.insert(), [dict(
            verify_id="verify-" + row.coupon_id, coupon_id=row.coupon_id, verify_status="valid",
            verify_time=at, poi_id="poi-verify", raw_payload={}) for row in coupon_rows])
        session.execute(text("CREATE TABLE dashboard_missing_fee_perf_unrelated AS "
            "SELECT item AS id, '2026-08'::text AS month, item::bigint AS fee_cent, "
            "repeat('synthetic immutable published evidence ',8) AS evidence "
            "FROM generate_series(1,100000) item"))
        session.execute(m.SettlementStatement.__table__.insert(), [dict(
            statement_id=f"outside-bill-{index}", store_id=f"outside-store-{index}", statement_month="2026-08",
            is_current=True) for index in range(10000)])
        session.commit()
        manifest = {"schema_version": 1, "request_id": f"synthetic-{coupon_count}-perf", "approval_ref": "DYDATA-104/test",
                    "actor": "ops:synthetic-test", "coupons": [{
                        "coupon_id": row.coupon_id, "order_id": row.order_id, "raw_order_id": row.raw_order_id,
                        "raw_coupon_id": row.id, "business_month": "2026-09", "expected_sale_store_id": "store-sale",
                        "expected_verify_store_id": "store-verify", "verify_id": "verify-" + row.coupon_id,
                        "verify_time": repair.canonical(at)} for row in coupon_rows]}
        session.rollback()
        exclusions = {"schema_version": 1, "groups": {name: {"coupon_ids": [], "count": 0, "sha256": repair.digest([])}
                                                      for name in repair.EXCLUSION_GROUPS}}
        phase_metrics = []
        query_count = [0]
        def count_statement(*_):
            query_count[0] += 1
        event.listen(pg_engine, "after_cursor_execute", count_statement)
        def measured(label, function):
            def run(*args, **kwargs):
                began, before_count = time.monotonic(), query_count[0]
                try:
                    return function(*args, **kwargs)
                finally:
                    phase_metrics.append({"phase": label, "seconds": round(time.monotonic() - began, 3),
                                          "sql_statements": query_count[0] - before_count})
            return run
        monkeypatch.setattr(repair, "_preview", measured("quote_and_dependencies", repair._preview))
        monkeypatch.setattr(repair, "_outside_financial_fingerprint", measured("outside_financial_fingerprint", repair._outside_financial_fingerprint))
        monkeypatch.setattr(s, "rebuild_dual_fee_results", measured("default_exact_writer", s.rebuild_dual_fee_results))
        started = time.monotonic()
        try:
            report = preview(session, manifest, exclusions)
        except repair.MissingFeeBudgetError:
            receipt = {"coupon_count": coupon_count, "direction_count": 2 * coupon_count, "budget": repair.BUDGET,
                       "preview_seconds": round(time.monotonic() - started, 3), "apply_seconds": 0,
                       "outcome": "preview-budget-refused", "unrelated_publication_rows": 100000,
                       "unrelated_bill_rows": 10000, "database": "disposable_loopback_postgresql", "production": False,
                       "phase_metrics": phase_metrics}
            assert counts(session) == (0, 0, 0, 0, 0)
            (tmp_path / f"missing-fee-{coupon_count}-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            print(f"{coupon_count} representative budget receipt: " + json.dumps(receipt))
            event.remove(pg_engine, "after_cursor_execute", count_statement)
            return
        preview_elapsed = time.monotonic() - started
        started = time.monotonic()
        try:
            applied = apply(session, manifest, exclusions, report["preview_hash"])
            outcome = "applied"
            assert applied["financial_before"] == applied["financial_after"]
            assert counts(session) == (2 * coupon_count, 2 * coupon_count, 0, 1, 0)
        except repair.MissingFeeBudgetError:
            outcome = "budget-refused"
            assert counts(session) == (0, 0, 0, 0, 0)
        except DBAPIError as exc:
            assert getattr(exc.orig, "sqlstate", getattr(exc.orig, "pgcode", None)) == "57014"
            outcome = "statement-budget-refused"
            assert counts(session) == (0, 0, 0, 0, 0)
        receipt = {"coupon_count": coupon_count, "direction_count": 2 * coupon_count, "budget": repair.BUDGET,
                   "unrelated_publication_rows": 100000, "unrelated_bill_rows": 10000,
                   "preview_seconds": round(preview_elapsed, 3), "apply_seconds": round(time.monotonic() - started, 3),
                   "outcome": outcome, "database": "disposable_loopback_postgresql", "production": False,
                   "phase_metrics": phase_metrics}
        (tmp_path / f"missing-fee-{coupon_count}-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(f"{coupon_count} representative budget receipt: " + json.dumps(receipt))
        event.remove(pg_engine, "after_cursor_execute", count_statement)


def test_postgres_remaining_wall_budget_clamps_statement_timeout(pg_engine, monkeypatch):
    with Session(pg_engine, autoflush=False) as session:
        manifest, exclusions = setup_batch(session)
        report = preview(session, manifest, exclusions)
        original = repair._preview
        def near_deadline(session, request, started):
            quoted = original(session, request, started)
            elapsed = time.monotonic() - started
            offset = 29.8 - elapsed
            monkeypatch.setattr(repair, "time", SimpleNamespace(monotonic=lambda: time.monotonic() + offset))
            session.execute(text("SELECT pg_sleep(1)"))
            return quoted
        monkeypatch.setattr(repair, "_preview", near_deadline)
        started = time.monotonic()
        with pytest.raises(DBAPIError) as error:
            apply(session, manifest, exclusions, report["preview_hash"])
        assert getattr(error.value.orig, "sqlstate", getattr(error.value.orig, "pgcode", None)) == "57014"
        assert time.monotonic() - started < 3
        assert counts(session) == (0, 0, 0, 0, 0)
