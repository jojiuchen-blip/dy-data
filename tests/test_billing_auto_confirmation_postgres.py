"""Dedicated-schema PostgreSQL concurrency gate for automatic confirmation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import event, func, select, text, insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import FinanceOperationAudit, SettlementStatement, SettlementStatementConfirmation
from apps.worker import billing_auto_confirmation as service
from test_billing_auto_confirmation import (
    NOW, seed_ready_bills, seed_negative_adjustments, seed_many_bills, seed_zero_bill,
    assert_replay_read_only_with_commit_hook,
)
from test_dashboard_publication_finance_postgres import POSTGRES_URL, postgres_session

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")


@pytest.mark.parametrize("mode", ["orm", "sql"])
def test_postgres_replay_read_only_never_runs_commit_hooks(postgres_session, monkeypatch, mode):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    assert_replay_read_only_with_commit_hook(factory, mode)


def test_postgres_one_winner_for_same_reviewed_batch(postgres_session, monkeypatch):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    preview = service.preview_auto_confirmation(factory, now=NOW)
    assert preview["counts"] == {"candidate": 2}
    barrier = Barrier(2)

    def apply():
        barrier.wait(timeout=5)
        try:
            return service.apply_auto_confirmation(factory, now=NOW, preview_hash=preview["preview_hash"])["confirmed_count"]
        except service.AutoConfirmationConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply) for _ in range(2)]
        outcomes = [future.result(timeout=15) for future in futures]
        assert outcomes.count(2) == 1 and all(value in (0, 2, "conflict") for value in outcomes)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 2
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type == "AUTO_CONFIRM_STATEMENT")) == 2


def test_postgres_manual_confirmation_while_auto_waits_keeps_manual_fact(postgres_session, monkeypatch):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    preview = service.preview_auto_confirmation(factory, now=NOW)
    waiting = Event()
    engine = postgres_session.get_bind()

    def before_cursor(_connection, _cursor, statement, _parameters, _context, _many):
        if "FOR UPDATE" in statement and "FROM settlement_statement " in statement:
            waiting.set()

    with factory() as manual:
        bill = manual.scalar(select(SettlementStatement).with_for_update())
        manual.add(SettlementStatementConfirmation(confirmation_id="manual-wins",
            statement_id=bill.statement_id, fee_direction=1, confirmed_amount_cent=1000,
            confirmed_by="manual-user", confirmed_at=NOW))
        event.listen(engine, "before_cursor_execute", before_cursor)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(service.apply_auto_confirmation, factory,
                    now=NOW, preview_hash=preview["preview_hash"])
                assert waiting.wait(timeout=5)
                manual.commit()
                with pytest.raises(service.AutoConfirmationConflict, match="preview changed"):
                    pending.result(timeout=15)
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor)
    with factory() as session:
        rows = list(session.scalars(select(SettlementStatementConfirmation)))
        assert len(rows) == 1 and rows[0].confirmed_by == "manual-user"
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type == "AUTO_CONFIRM_STATEMENT")) == 0


def test_postgres_explicit_hold_persists_across_new_sessions(postgres_session, monkeypatch):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    with factory.begin() as session:
        service.set_confirmation_hold(session, store_id="billing-store", month="2026-08", direction=1,
            active=True, reason="pending correction", evidence_reference="synthetic-evidence",
            operator="synthetic-admin", request_key="pg-review-hold")
    preview = service.preview_auto_confirmation(factory, now=NOW)
    assert preview["rows"][0]["reason"] == "EXPLICIT_REVIEW_HOLD"
    assert service.apply_auto_confirmation(factory, now=NOW, preview_hash=preview["preview_hash"])["confirmed_count"] == 1


def test_postgres_negative_management_is_zero_and_promotion_stays_signed(postgres_session, monkeypatch):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    seed_negative_adjustments(factory)
    preview = service.preview_auto_confirmation(factory, now=NOW)
    assert preview["counts"] == {"candidate": 2}
    assert [row["amount_cent"] for row in preview["rows"]] == [-1000, 0]
    service.apply_auto_confirmation(factory, now=NOW, preview_hash=preview["preview_hash"])
    with factory() as session:
        assert [(row.fee_direction, row.confirmed_amount_cent) for row in session.scalars(
            select(SettlementStatementConfirmation).order_by(SettlementStatementConfirmation.fee_direction))] == [(1, -1000), (2, 0)]


def test_postgres_fifty_bill_batch_has_fixed_data_reads(postgres_session, monkeypatch):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    seed_many_bills(factory, 50)
    counts, queries = [], []
    engine = postgres_session.get_bind()
    def count(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            queries.append(statement)
    event.listen(engine, "before_cursor_execute", count)
    try:
        for size in (1, 5, 50):
            queries.clear()
            result = service.preview_auto_confirmation(factory, now=NOW, limit=size)
            assert result["counts"] == {"candidate": size * 2}
            counts.append(len(queries))
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(set(counts)) == 1 and max(counts) <= 25, counts


def test_postgres_wall_budget_after_first_write_rolls_back_every_fact(postgres_session, monkeypatch):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    preview = service.preview_auto_confirmation(factory, now=NOW)
    clock = [0.0]
    monkeypatch.setattr(service, "_wall_clock", lambda: clock[0])
    engine = postgres_session.get_bind()
    def expire(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO"):
            clock[0] = 31.0
    event.listen(engine, "after_cursor_execute", expire)
    try:
        with pytest.raises(service.AutoConfirmationConflict, match="wall budget"):
            service.apply_auto_confirmation(factory, now=NOW, preview_hash=preview["preview_hash"])
    finally:
        event.remove(engine, "after_cursor_execute", expire)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 0
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type.in_(("AUTO_CONFIRM_BATCH", "AUTO_CONFIRM_STATEMENT")))) == 0


def test_postgres_empty_generated_slot_amid_other_store_overlay_is_legitimate_zero(postgres_session, monkeypatch):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    seed_zero_bill(factory)
    preview = service.preview_auto_confirmation(factory, now=NOW, store_ids=("billing-store",))
    assert preview["counts"] == {"candidate": 2} and [row["amount_cent"] for row in preview["rows"]] == [0, 0]
    assert service.apply_auto_confirmation(factory, now=NOW, store_ids=("billing-store",),
        preview_hash=preview["preview_hash"])["confirmed_count"] == 2


def test_postgres_remaining_budget_clamps_streaming_cursor_without_invalid_set(postgres_session, monkeypatch):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    clock, observed = [0.0], []
    monkeypatch.setattr(service, "_wall_clock", lambda: clock[0])
    engine = postgres_session.get_bind()
    def advance(connection, _cursor, statement, _parameters, _context, _many):
        if "FROM settlement_statement_entry" in statement:
            clock[0] = 26.0
        if "sparse_authority" in statement:
            with connection.connection.dbapi_connection.cursor() as cursor:
                cursor.execute("SELECT setting::integer FROM pg_settings WHERE name = 'statement_timeout'")
                observed.append(cursor.fetchone()[0])
    event.listen(engine, "after_cursor_execute", advance)
    try:
        assert service.preview_auto_confirmation(factory, now=NOW)["counts"] == {"candidate": 2}
    finally:
        event.remove(engine, "after_cursor_execute", advance)
    assert observed and max(observed) <= 4000


def test_postgres_deferred_trigger_runs_inside_remaining_sql_budget_and_rolls_back(postgres_session, monkeypatch):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    preview = service.preview_auto_confirmation(factory, now=NOW)
    engine = postgres_session.get_bind()
    with engine.begin() as connection:
        connection.execute(text("CREATE FUNCTION billing_confirmation_commit_delay() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(0.2); RETURN NEW; END $$"))
        connection.execute(text("CREATE CONSTRAINT TRIGGER billing_confirmation_commit_delay "
            "AFTER INSERT ON settlement_statement_confirmation DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION billing_confirmation_commit_delay()"))
    clock, forced = [0.0], []
    monkeypatch.setattr(service, "_wall_clock", lambda: clock[0])
    def late(_conn, _cursor, sql, _parameters, _context, _many):
        if sql.lstrip().upper().startswith("INSERT INTO SETTLEMENT_STATEMENT_CONFIRMATION"):
            clock[0] = 29.95
    def forcing(_conn, _cursor, sql, _parameters, _context, _many):
        if sql.lstrip().upper() == "SET CONSTRAINTS ALL IMMEDIATE":
            forced.append(sql)
    event.listen(engine, "after_cursor_execute", late)
    event.listen(engine, "before_cursor_execute", forcing)
    try:
        with pytest.raises(DBAPIError) as error:
            service.apply_auto_confirmation(factory, now=NOW, preview_hash=preview["preview_hash"])
        assert error.value.orig.sqlstate == "57014"
    finally:
        event.remove(engine, "after_cursor_execute", late)
        event.remove(engine, "before_cursor_execute", forcing)
    assert forced == ["SET CONSTRAINTS ALL IMMEDIATE"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 0
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type.in_(("AUTO_CONFIRM_BATCH", "AUTO_CONFIRM_STATEMENT")))) == 0


@pytest.mark.parametrize("hook,mode", [("before_commit", "orm"), ("before_commit", "sql"),
                                       ("after_flush_postexec", "orm")])
def test_postgres_final_seal_rejects_late_orm_and_sql_hooks(postgres_session, monkeypatch, hook, mode):
    factory = seed_ready_bills(postgres_session, monkeypatch)
    preview = service.preview_auto_confirmation(factory, now=NOW)
    injected = []
    values = dict(audit_id="late-confirmation-test-hook", operation_type="SYNTHETIC_LATE_HOOK",
        target_type="SYNTHETIC", target_id="synthetic-target", operator_id="synthetic-test",
        operator_role=1, result_status=1, request_id="synthetic-hook")
    def inject(session, *_args):
        if service._DEADLINE_KEY not in session.info or session.info.get("late_hook_injected"):
            return
        session.info["late_hook_injected"] = True
        injected.append(mode)
        if mode == "orm":
            session.add(FinanceOperationAudit(**values))
        else:
            session.execute(insert(FinanceOperationAudit).values(**values))
    event.listen(Session, hook, inject)
    try:
        with pytest.raises(service.AutoConfirmationConflict, match="seal|pending ORM"):
            service.apply_auto_confirmation(factory, now=NOW, preview_hash=preview["preview_hash"])
    finally:
        event.remove(Session, hook, inject)
    assert injected == [mode]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 0
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type.in_(("AUTO_CONFIRM_BATCH", "AUTO_CONFIRM_STATEMENT", "SYNTHETIC_LATE_HOOK")))) == 0
