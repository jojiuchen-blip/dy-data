"""Real PostgreSQL authority queries and confirmation/capture row-lock ordering."""
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.models import Base, SettlementStatement, SettlementStatementConfirmation
from apps.worker.billing_source_capture import collect_billing_sources
from test_protected_billing_authority import (
    _seed, test_whole_confirmed_status_two_bill_and_negative_entry_override_current_chain as _assert_authority,
    test_nested_monthly_lines_match_authority_when_replacement_and_normal_share_a_group as _assert_lines,
    test_adjustments_use_exact_frozen_basis_instead_of_pointer_reanchoring as _assert_adjustment,
)


@pytest.fixture()
def postgres_engine(request, monkeypatch):
    url = os.getenv("DYDATA_PROTECTED_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set DYDATA_PROTECTED_TEST_DATABASE_URL to a disposable local database")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database.endswith("_test")
    schema = "protected_authority_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000"})
    try:
        if getattr(request, "param", None) == "migration":
            isolated = parsed.update_query_dict({"options": f"-csearch_path={schema}"})
            monkeypatch.setenv("DY_DATABASE_URL", isolated.render_as_string(hide_password=False))
            root = Path(__file__).resolve().parents[1]
            config = Config(str(root / "alembic.ini"))
            config.set_main_option("script_location", str(root / "alembic"))
            command.upgrade(config, "head")
        else:
            Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("store,month", (("store-a", "2026-08"), ("store-b", "2026-09")))
def test_postgres_whole_bill_authority_excludes_replacement_chain(postgres_engine, store, month):
    with Session(postgres_engine, autoflush=False) as session:
        _assert_authority(session, store, month)


def test_postgres_nested_lines_share_economic_authority(postgres_engine):
    with Session(postgres_engine, autoflush=False) as session:
        _assert_lines(session)


@pytest.mark.parametrize("basis,allowed", (("old-promotion", True), ("replacement-1", False)))
def test_postgres_adjustment_basis_is_preserved_or_fails_closed(postgres_engine, basis, allowed):
    with Session(postgres_engine, autoflush=False) as session:
        _assert_adjustment(session, basis, allowed)


@pytest.mark.parametrize("postgres_engine", ("migration",), indirect=True)
def test_migrated_postgres_authority_and_fail_closed_leave_sources_unchanged(postgres_engine):
    with Session(postgres_engine, autoflush=False) as session:
        _assert_adjustment(session, "replacement-1", False)
        counters = session.execute(text("SELECT source_name,generation FROM dashboard_publication_source_counters ORDER BY source_name")).all()
        from apps.worker.protected_billing_authority import ProtectedBillingAuthorityError
        with pytest.raises(ProtectedBillingAuthorityError, match="unapproved replacement"):
            collect_billing_sources(session, months=("2026-08", "2026-09"))
        assert session.execute(text("SELECT source_name,generation FROM dashboard_publication_source_counters ORDER BY source_name")).all() == counters


@pytest.mark.parametrize("postgres_engine", ("metadata", "migration"), indirect=True)
def test_postgres_publication_only_complete_apply(postgres_engine, monkeypatch):
    from test_settlement_publication_only import test_apply_publishes_without_fee_rebuild_and_versions_only_unprotected_bill as apply
    with Session(postgres_engine, autoflush=False) as session:
        apply(session, monkeypatch)


def test_postgres_publication_only_atomic_billing_rollback(postgres_engine, monkeypatch):
    from test_settlement_publication_only import test_billing_failure_rolls_back_publication_and_statement_switch as rollback
    with Session(postgres_engine, autoflush=False) as session:
        rollback(session, monkeypatch)


def test_postgres_publication_only_refuses_existing_heavy_claim_lock(postgres_engine):
    from test_settlement_publication_only import _setup
    from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY
    from apps.worker.settlement_publication_only import preview_settlement_publication, apply_settlement_publication
    from apps.api.dy_api.models import JobRun
    from sqlalchemy import func

    with Session(postgres_engine, autoflush=False) as session:
        factory = _setup(session)
        preview = preview_settlement_publication(factory, months=("2026-08",))
        with postgres_engine.begin() as other:
            assert other.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY)))
            with pytest.raises(RuntimeError, match="claim is unavailable"):
                apply_settlement_publication(factory, months=("2026-08",), preview_hash=preview["preview_hash"])
        assert session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_postgres_capture_waits_for_confirmation_then_rereads_whole_bill(postgres_engine):
    with Session(postgres_engine, autoflush=False) as setup:
        _seed(setup)
        setup.execute(delete(SettlementStatementConfirmation))
        setup.commit()
    started = Event()
    backend_pid = []
    def capture():
        with Session(postgres_engine, autoflush=False) as session:
            backend_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            return collect_billing_sources(session, months=("2026-08", "2026-09"), slots=(("store-a", "2026-08"),))
    with Session(postgres_engine, autoflush=False) as confirmer:
        confirmer.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "frozen-bill").with_for_update())
        confirmer.add(SettlementStatementConfirmation(
            confirmation_id="racing-confirmation", statement_id="frozen-bill", fee_direction=1,
            confirmation_status=1, confirmed_amount_cent=800, confirmed_by="synthetic",
        ))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(capture)
            assert started.wait(5)
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline:
                with postgres_engine.connect() as observer:
                    waiting = observer.execute(text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid=:pid"), {"pid": backend_pid[0]}).scalar()
                if waiting:
                    break
                time.sleep(0.02)
            assert waiting, "capture did not wait for the bill confirmation row lock"
            confirmer.commit()
            sources = future.result(timeout=10)
    assert {row.source_record_id for row in sources} == {"old-promotion", "old-management", "frozen-negative", "normal"}
