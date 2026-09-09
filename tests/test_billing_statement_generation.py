"""Pending billing generation must not confirm or mutate financial facts."""
from dataclasses import replace
import importlib
import importlib.util
import sys
import os
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import select, func, event, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from dy_api.auth import AuthContext, get_current_user
from dy_api.main import create_app
from dy_api.routes._data import DashboardDataStore, get_session_dependency
from dy_api.routes.dashboard import confirm_store_settlement

from apps.api.dy_api.models import (
    Base, DimStore, FinanceOperationAudit, InvoiceRecord, PromotionInvoiceAllocation,
    SettlementStatement, SettlementStatementEntry,
    SettlementStatementLine, SettlementStatementConfirmation,
    SettlementProjectionGeneration, SettlementProjectionActive,
    SettlementProjectionPartitionManifest, SettlementMonthlyOverlay,
)
from apps.worker.settlement import StatementSource
from apps.api.dy_api.models import StoreFinanceProfile, SettlementDispute


def test_first_bill_captures_basic_finance_sap(db_session):
    sources = _seed(db_session)
    db_session.add(StoreFinanceProfile(profile_id="basic", store_id="billing-store",
        profile_type=1, store_name_snapshot="Billing Store", sap_code="SAP-123"))
    db_session.commit()
    _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    bill = db_session.scalar(select(SettlementStatement))
    assert (bill.sap_code_snapshot, bill.store_snapshot_profile_id) == ("SAP-123", "basic")


def test_history_without_current_fails_closed(db_session):
    sources = _seed(db_session)
    _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    db_session.scalar(select(SettlementStatement)).is_current = False
    db_session.commit()
    result = _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    assert result["blocked"] == 1
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 1


@pytest.mark.parametrize("dispute_status", [1, 2, 3, 4])
def test_disputed_bill_is_protected_from_regeneration(db_session, dispute_status):
    sources = _seed(db_session)
    _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    bill = db_session.scalar(select(SettlementStatement))
    db_session.add(SettlementDispute(dispute_id="dispute", statement_id=bill.statement_id,
        store_id=bill.store_id, statement_month=bill.statement_month, fee_direction=1,
        dispute_type=1, status=dispute_status, description="test dispute", contact_name="test",
        contact_phone_ciphertext="synthetic", submitted_by="test"))
    db_session.commit()
    changed = _publish_changed(db_session, sources)
    result = _module().generate_pending_statements(db_session, generation_id="billing-g2", sources=changed)
    assert result["protected"] == 1
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 1


def _module():
    assert importlib.util.find_spec("apps.worker.billing_statements") is not None, "pending billing generator is missing"
    return importlib.import_module("apps.worker.billing_statements")


def _seed(session):
    session.add(DimStore(store_id="billing-store", store_name="Billing Store"))
    session.add(SettlementProjectionGeneration(generation_id="billing-g1", state="published", input_fingerprint="billing-g1"))
    session.flush()
    session.add(SettlementProjectionActive(projection_name="settlement", generation_id="billing-g1"))
    session.add(SettlementProjectionPartitionManifest(
        generation_id="billing-g1", artifact="monthly", partition_key="2026-08",
        source_kind="overlay", data_generation_id="billing-g1",
    ))
    for scope, product_type in (("all", "all"), ("all", "type"), ("scope", "all"), ("scope", "type")):
        session.add(SettlementMonthlyOverlay(
            generation_id="billing-g1", partition_key="2026-08", month="2026-08",
            store_id="billing-store", product_scope=scope, product_type=product_type,
            promotion_base_cent=10000, promotion_original_fee_cent=1000, promotion_net_fee_cent=1000,
            management_base_cent=10000, management_original_fee_cent=1000, management_net_fee_cent=1000,
        ))
    session.commit()
    return tuple(StatementSource(
        source_type=1, source_record_id=f"fee-{direction}", original_fee_result_id=f"fee-{direction}",
        coupon_id="coupon", order_id="order", fee_direction=direction,
        original_business_month="2026-08", posting_month="2026-08", store_id="billing-store",
        product_scope="scope", product_type="type", base_amount_cent=10000,
        fee_amount_cent=1000, source_amount_cent=10000, rule_version="v1",
    ) for direction in (1, 2))


def test_published_snapshot_generates_pending_three_layers_and_replays(db_session):
    sources = _seed(db_session)
    api = _module()
    result = api.generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    db_session.commit()
    assert result["created"] == 1
    statement = db_session.scalar(select(SettlementStatement))
    assert statement.statement_status == 2
    assert statement.locked_at is None and statement.confirmed_at is None
    assert statement.promotion_net_fee_cent == statement.management_net_fee_cent == 1000
    assert db_session.scalar(select(func.count()).select_from(SettlementStatementLine)) == 2
    assert db_session.scalar(select(func.count()).select_from(SettlementStatementEntry)) == 2
    assert db_session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 0
    replay = api.generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    assert replay["unchanged"] == 1
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 1


def test_projection_mismatch_rolls_back_all_billing_writes(db_session):
    sources = _seed(db_session)
    api = _module()
    with pytest.raises(ValueError, match="projection"):
        api.generate_pending_statements(db_session, generation_id="billing-g1", sources=(replace(sources[0], fee_amount_cent=999), sources[1]))
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 0


@pytest.mark.parametrize("protected", ["confirmed", "locked"])
def test_existing_financial_facts_are_not_replaced(db_session, protected):
    sources = _seed(db_session)
    api = _module()
    api.generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    statement = db_session.scalar(select(SettlementStatement))
    if protected == "locked":
        statement.statement_status = 4
    else:
        db_session.add(SettlementStatementConfirmation(
            confirmation_id="billing-confirmed", statement_id=statement.statement_id,
            fee_direction=1, confirmation_status=1, confirmed_amount_cent=1000, confirmed_by="store",
        ))
    db_session.commit()
    outcome = api.generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    assert outcome["protected"] == 1
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 1


def test_unpublished_generation_cannot_generate_statements(db_session):
    sources = _seed(db_session)
    db_session.get(SettlementProjectionGeneration, "billing-g1").state = "staging"
    db_session.commit()
    with pytest.raises(ValueError, match="published"):
        _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)


def test_missing_frozen_sources_is_blocked_and_audited_idempotently(db_session):
    _seed(db_session)
    api = _module()
    for _ in range(2):
        outcome = api.generate_pending_statements(db_session, generation_id="billing-g1")
        assert outcome["blocked"] == 1 and outcome["generated"] == 0
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 0
    audit = db_session.scalar(select(FinanceOperationAudit))
    assert audit is not None
    assert audit.after_snapshot["reason"] == "FROZEN_SOURCES_MISSING"
    assert db_session.scalar(select(func.count()).select_from(FinanceOperationAudit)) == 1


def test_stale_published_generation_is_rejected(db_session):
    sources = _seed(db_session)
    db_session.add(SettlementProjectionGeneration(generation_id="billing-g2", state="published", input_fingerprint="billing-g2"))
    db_session.flush()
    db_session.get(SettlementProjectionActive, "settlement").generation_id = "billing-g2"
    db_session.commit()
    with pytest.raises(ValueError, match="published"):
        _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 0


def _publish_changed(db_session, sources):
    db_session.add(SettlementProjectionGeneration(generation_id="billing-g2", state="published", input_fingerprint="billing-g2"))
    db_session.flush()
    db_session.add(SettlementProjectionPartitionManifest(
        generation_id="billing-g2", artifact="monthly", partition_key="2026-08", source_kind="overlay", data_generation_id="billing-g2",
    ))
    for scope, product_type in (("all", "all"), ("all", "type"), ("scope", "all"), ("scope", "type")):
        db_session.add(SettlementMonthlyOverlay(
            generation_id="billing-g2", partition_key="2026-08", month="2026-08", store_id="billing-store",
            product_scope=scope, product_type=product_type, promotion_base_cent=10000,
            promotion_original_fee_cent=900, promotion_net_fee_cent=900,
            management_base_cent=10000, management_original_fee_cent=1000, management_net_fee_cent=1000,
        ))
    db_session.get(SettlementProjectionActive, "settlement").generation_id = "billing-g2"
    db_session.commit()
    return (replace(sources[0], source_record_id="fee-1-v2", fee_amount_cent=900), sources[1])


def test_changed_pending_bill_creates_version_without_rewriting_old_entries(db_session):
    sources = _seed(db_session)
    api = _module()
    api.generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    db_session.commit()
    old = db_session.scalar(select(SettlementStatement))
    old_id = old.statement_id
    changed = _publish_changed(db_session, sources)
    result = api.generate_pending_statements(db_session, generation_id="billing-g2", sources=changed)
    db_session.commit()
    assert result["generated"] == 1
    current = db_session.scalar(select(SettlementStatement).where(SettlementStatement.is_current.is_(True)))
    assert current.version_no == 2 and current.supersedes_statement_id == old_id
    assert current.promotion_net_fee_cent == 900
    db_session.refresh(old)
    assert old.is_current is False and old.promotion_net_fee_cent == 1000
    old_entries = list(db_session.scalars(select(SettlementStatementEntry).where(SettlementStatementEntry.statement_id == old_id)))
    assert len(old_entries) == 2 and sum(row.fee_amount_cent for row in old_entries) == 2000
    assert api.generate_pending_statements(db_session, generation_id="billing-g2", sources=changed)["unchanged"] == 1


def test_confirmation_after_source_replacement_blocks_publication(db_session):
    sources = _seed(db_session)
    api = _module()
    api.generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    db_session.commit()
    old = db_session.scalar(select(SettlementStatement))
    changed = _publish_changed(db_session, sources)
    # The source writer committed before a user confirmed the old statement.
    db_session.add(SettlementStatementConfirmation(
        confirmation_id="late-confirmation", statement_id=old.statement_id,
        fee_direction=1, confirmation_status=1, confirmed_amount_cent=1000,
        confirmed_by="store",
    ))
    db_session.commit()
    result = api.generate_pending_statements(db_session, generation_id="billing-g2", sources=changed)
    assert result["blocked"] == 1
    assert result["protected"] == 1
    assert result["generated"] == 0
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 1


def test_protected_original_retained_by_frozen_adjustment_is_not_drift(db_session):
    sources = _seed(db_session)
    api = _module()
    api.generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    db_session.scalar(select(SettlementStatement)).statement_status = 4
    db_session.commit()
    adjusted = (replace(sources[0], source_type=2, source_record_id="anchor-adjustment",
                        original_fee_result_id=sources[0].source_record_id), sources[1])
    result = api.generate_pending_statements(db_session, generation_id="billing-g1", sources=adjusted)
    assert result["blocked"] == 0 and result["protected"] == 1
    assert result["generated"] == 0


def test_empty_captured_slot_replaces_pending_bill_with_zero(db_session):
    sources = _seed(db_session)
    api = _module()
    api.generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    db_session.commit()
    _publish_changed(db_session, sources)
    for row in db_session.scalars(select(SettlementMonthlyOverlay).where(SettlementMonthlyOverlay.generation_id == "billing-g2")):
        row.promotion_base_cent = row.management_base_cent = 0
        row.promotion_original_fee_cent = row.management_original_fee_cent = 0
        row.promotion_net_fee_cent = row.management_net_fee_cent = 0
    db_session.commit()
    result = api.generate_pending_statements(db_session, generation_id="billing-g2", sources=(), slots=(("billing-store", "2026-08"),))
    assert result["generated"] == 1
    current = db_session.scalar(select(SettlementStatement).where(SettlementStatement.is_current.is_(True)))
    assert current.version_no == 2 and current.promotion_net_fee_cent == current.management_net_fee_cent == 0


@pytest.mark.parametrize("operation", ["confirmations", "disputes"])
def test_confirmation_api_locks_and_refreshes_statement_before_writing(db_session, monkeypatch, operation):
    sources = _seed(db_session)
    _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    db_session.commit()
    statement = db_session.scalar(select(SettlementStatement))
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    app = create_app()
    app.dependency_overrides[get_session_dependency] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="billing-user", username="billing-user", display_name="Billing User",
        role="store", store_ids=("billing-store",), auth_type="user", store_scope_mode="assigned",
    )
    locked_reads = []
    def capture(orm_state):
        query = orm_state.statement
        if getattr(query, "_for_update_arg", None) is not None and "settlement_statement" in str(query):
            locked_reads.append(bool(orm_state.execution_options.get("populate_existing")))
    event.listen(db_session, "do_orm_execute", capture)
    try:
        with TestClient(app) as client:
            payload = {"feeDirection": "PROMOTION", "confirmedAmountCent": 1000, "readVersion": 1}
            if operation == "disputes":
                payload = {"feeDirection": "PROMOTION", "disputeType": "AMOUNT_ERROR",
                    "description": "synthetic amount discrepancy", "contactName": "Test",
                    "contactPhone": "13812345678", "disputedAmountCent": 100,
                    "orders": [{"orderId": "order", "couponId": "coupon", "disputedAmountCent": 100}], "readVersion": 1}
            response = client.post(f"/api/v1/store-settlements/{statement.statement_id}/{operation}",
                                   json=payload,
                                   headers={"Idempotency-Key": "billing-confirmation-lock-test"})
        assert response.status_code == 200, response.text
        assert locked_reads and all(locked_reads), "confirmation must lock and refresh the immutable statement version"
    finally:
        event.remove(db_session, "do_orm_execute", capture)


def test_confirmation_key_cannot_replay_another_statement(db_session):
    sources = _seed(db_session)
    _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    bill = db_session.scalar(select(SettlementStatement))
    db_session.add(SettlementStatement(statement_id="other-bill", store_id="billing-store",
        statement_month="2026-09", version_no=1, is_current=True, statement_status=2,
        promotion_original_fee_cent=1000, promotion_net_fee_cent=1000))
    db_session.commit()
    args = dict(payload={"feeDirection": "PROMOTION", "confirmedAmountCent": 1000, "readVersion": 1},
        request=Request({"type": "http", "method": "POST", "path": "/", "headers": []}),
        idempotency_key="confirmation-cross-statement-test",
        current_user=AuthContext(user_id="test", username="test", display_name="Test", role="store",
            store_ids=("billing-store",), auth_type="user", store_scope_mode="assigned"),
        store=DashboardDataStore(db_session))
    confirm_store_settlement(statement_id=bill.statement_id, **args)
    with pytest.raises(HTTPException) as error:
        confirm_store_settlement(statement_id="other-bill", **args)
    assert error.value.status_code == 409


@pytest.mark.parametrize("operation", ["withdraw", "transition"])
def test_dispute_mutation_locks_statement_then_dispute(db_session, monkeypatch, operation):
    from dy_api.routes.dashboard import withdraw_store_settlement_dispute, transition_admin_dispute, _encrypt_dispute_phone
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    sources = _seed(db_session)
    _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    bill = db_session.scalar(select(SettlementStatement))
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    db_session.add(SettlementDispute(dispute_id="mutable-dispute", statement_id=bill.statement_id,
        store_id=bill.store_id, statement_month=bill.statement_month, fee_direction=1,
        dispute_type=1, status=1, description="synthetic", contact_name="test",
        contact_phone_ciphertext=_encrypt_dispute_phone("13812345678", request), submitted_by="test"))
    db_session.commit()
    locks = []
    def capture(state):
        if getattr(state.statement, "_for_update_arg", None) is not None:
            locks.append((str(state.statement), state.execution_options.get("populate_existing")))
    event.listen(db_session, "do_orm_execute", capture)
    try:
        function = withdraw_store_settlement_dispute if operation == "withdraw" else transition_admin_dispute
        function(dispute_id="mutable-dispute", request=request, idempotency_key="dispute-mutation-lock-test",
            payload={"reason": "withdraw", "resolutionNote": "review", "targetStatus": "IN_REVIEW", "readVersion": 1},
            current_user=AuthContext(user_id="test", username="test", display_name="Test",
                role="admin" if operation == "transition" else "store", store_ids=("billing-store",),
                auth_type="user", store_scope_mode="assigned", page_keys=("FIN05",)), store=DashboardDataStore(db_session))
        assert len(locks) >= 2
        assert "FROM settlement_statement" in locks[0][0] and locks[0][1]
        assert "FROM settlement_dispute" in locks[1][0] and locks[1][1]
        db_session.add(SettlementDispute(dispute_id="other-dispute", statement_id=bill.statement_id,
            store_id=bill.store_id, statement_month=bill.statement_month, fee_direction=1,
            dispute_type=1, status=1, description="synthetic", contact_name="test",
            contact_phone_ciphertext=_encrypt_dispute_phone("13812345678", request), submitted_by="test"))
        db_session.commit()
        with pytest.raises(HTTPException) as error:
            function(dispute_id="other-dispute", request=request, idempotency_key="dispute-mutation-lock-test",
                payload={"reason": "withdraw", "resolutionNote": "review", "targetStatus": "IN_REVIEW", "readVersion": 1},
                current_user=AuthContext(user_id="test", username="test", display_name="Test",
                    role="admin" if operation == "transition" else "store", store_ids=("billing-store",),
                    auth_type="user", store_scope_mode="assigned", page_keys=("FIN05",)), store=DashboardDataStore(db_session))
        assert error.value.status_code == 409
    finally:
        event.remove(db_session, "do_orm_execute", capture)


@pytest.mark.parametrize("superseded", [False, True])
def test_dispute_lock_targets_fixed_version_not_current_predicate(db_session, superseded):
    from sqlalchemy import update
    from dy_api.routes.dashboard import _lock_dispute_mutation
    sources = _seed(db_session)
    _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    bill = db_session.scalar(select(SettlementStatement))
    dispute = SettlementDispute(dispute_id="fixed-lock", statement_id=bill.statement_id,
        store_id=bill.store_id, statement_month=bill.statement_month, fee_direction=1,
        dispute_type=1, status=1, description="synthetic", contact_name="test",
        contact_phone_ciphertext="synthetic", submitted_by="test")
    db_session.add(dispute)
    db_session.commit()
    locks = []
    def capture(state):
        if getattr(state.statement, "_for_update_arg", None) is not None:
            locks.append(str(state.statement).split("WHERE", 1)[1])
            if superseded and len(locks) == 1:
                db_session.execute(update(SettlementStatement).where(
                    SettlementStatement.statement_id == bill.statement_id,
                ).values(is_current=False).execution_options(synchronize_session=False))
    event.listen(db_session, "do_orm_execute", capture)
    try:
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        if superseded:
            with pytest.raises(HTTPException) as error:
                _lock_dispute_mutation(db_session, dispute, request)
            assert error.value.status_code == 409
            assert len(locks) == 1
        else:
            _lock_dispute_mutation(db_session, dispute, request)
        assert "settlement_statement.statement_id =" in locks[0]
        assert "is_current" not in locks[0]
    finally:
        event.remove(db_session, "do_orm_execute", capture)


@pytest.fixture
def billing_pg():
    raw_url = os.getenv("DY_RELEASE_POSTGRES_URL")
    if not raw_url:
        pytest.skip("requires disposable release PostgreSQL service")
    url = make_url(raw_url)
    if not url.drivername.startswith("postgresql") or url.host not in {"127.0.0.1", "localhost"} or url.database != "dydata_release":
        pytest.fail("billing gate requires loopback dydata_release database")
    schema = f"billing_gate_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000 -c statement_timeout=15000"})
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        tables = {model.__table__ for model in (
            DimStore, FinanceOperationAudit, InvoiceRecord, PromotionInvoiceAllocation,
            SettlementDispute, StoreFinanceProfile,
            SettlementStatement, SettlementStatementEntry, SettlementStatementLine,
            SettlementStatementConfirmation, SettlementProjectionGeneration,
            SettlementProjectionActive, SettlementProjectionPartitionManifest, SettlementMonthlyOverlay,
        )}
        pending = list(tables)
        while pending:
            for foreign_key in pending.pop().foreign_keys:
                dependency = foreign_key.column.table
                if dependency not in tables:
                    tables.add(dependency)
                    pending.append(dependency)
        Base.metadata.create_all(engine, tables=list(tables))
        yield factory
    finally:
        engine.dispose()
        assert re.fullmatch(r"billing_gate_[0-9a-f]{32}", schema)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("winner", ["generation", "confirmation"])
def test_pg_confirmation_and_pending_generation_serialize(billing_pg, winner):
    factory = billing_pg
    with factory() as session:
        sources = _seed(session)
        _module().generate_pending_statements(session, generation_id="billing-g1", sources=sources)
        session.commit()
        old_id = session.scalar(select(SettlementStatement.statement_id))
        changed = _publish_changed(session, sources)
    reached = Event()
    release = Event()

    def confirm():
        with factory() as session:
            def on_query(state):
                if getattr(state.statement, "_for_update_arg", None) is not None:
                    reached.set()
            def before_commit(_session):
                reached.set()
                assert release.wait(5)
            if winner == "generation":
                event.listen(session, "do_orm_execute", on_query)
            else:
                event.listen(session, "before_commit", before_commit, once=True)
            try:
                confirm_store_settlement(
                    statement_id=old_id,
                    payload={"feeDirection": "PROMOTION", "confirmedAmountCent": 1000, "readVersion": 1},
                    request=Request({"type": "http", "method": "POST", "path": "/", "headers": []}),
                    idempotency_key="billing-pg-confirmation-0001",
                    current_user=AuthContext(user_id="billing-user", username="billing-user", display_name="Billing", role="store", store_ids=("billing-store",), auth_type="user", store_scope_mode="assigned"),
                    store=DashboardDataStore(session),
                )
                return 200
            except HTTPException as error:
                return error.status_code

    def generate():
        with factory.begin() as session:
            return _module().generate_pending_statements(session, generation_id="billing-g2", sources=changed)

    with ThreadPoolExecutor(max_workers=2) as executor:
        if winner == "generation":
            with factory() as session:
                result = _module().generate_pending_statements(session, generation_id="billing-g2", sources=changed)
                pending_confirmation = executor.submit(confirm)
                assert reached.wait(5)
                session.commit()
            assert pending_confirmation.result(timeout=10) == 409
            assert result["generated"] == 1
        else:
            pending_confirmation = executor.submit(confirm)
            assert reached.wait(5)
            pending_generation = executor.submit(generate)
            release.set()
            assert pending_confirmation.result(timeout=10) == 200
            assert pending_generation.result(timeout=10)["protected"] == 1
    with factory() as session:
        current = session.scalar(select(SettlementStatement).where(SettlementStatement.is_current.is_(True)))
        confirmations = session.scalar(select(func.count()).select_from(SettlementStatementConfirmation))
        assert current.version_no == (2 if winner == "generation" else 1)
        assert confirmations == (0 if winner == "generation" else 1)
