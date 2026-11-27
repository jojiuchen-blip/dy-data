"""A background close scans a committed evidence snapshot and queues once."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import JobRun, SettlementMonthClose
from apps.worker import month_close as close
from test_month_close_auto_bootstrap import MONTH, NOW, _seed
from test_month_close_auto_bootstrap import bootstrap_session  # noqa: F401
from test_protected_billing_authority_postgres import postgres_engine  # noqa: F401


@pytest.mark.parametrize("certified", (False, True))
def test_background_discovery_preserves_a_finished_input_and_its_attempts(bootstrap_session, monkeypatch, certified):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", str(certified))
    factory = _seed(bootstrap_session)

    job_id = close.ensure_month_close_job(factory, now=NOW, bounded=True)
    assert job_id
    with factory.begin() as session:
        job = session.get(JobRun, job_id)
        assert job.status == "queued"
        job.status = "failed"
        job.attempt_count = 3
        job.max_attempts = 3
        assert bool(job.metadata_json.get("store_evidence_version_id")) is certified

    assert close.ensure_month_close_job(factory, now=NOW) == job_id
    assert close.ensure_month_close_job(factory, now=NOW, bounded=True) == job_id
    with factory() as session:
        assert session.get(JobRun, job_id).status == "failed"
        assert session.get(JobRun, job_id).attempt_count == 3
        assert list(session.scalars(select(JobRun.job_id).where(JobRun.job_name == "settlement_rebuild"))) == [job_id]


def test_background_deadline_cannot_queue_a_partially_scanned_month(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session)
    elapsed = [0.0]
    monkeypatch.setattr(close, "time", SimpleNamespace(monotonic=lambda: elapsed[0]))
    original_digest = close._calculation_inputs_digest

    def expired_digest(*args, **kwargs):
        digest = original_digest(*args, **kwargs)
        elapsed[0] += close.MONTH_CLOSE_DISCOVERY_SECONDS + 1
        return digest

    monkeypatch.setattr(close, "_calculation_inputs_digest", expired_digest)
    with pytest.raises(TimeoutError, match="month close discovery deadline exceeded"):
        close.ensure_month_close_job(factory, now=NOW, bounded=True)
    with factory() as session:
        assert session.scalar(select(JobRun.job_id).where(JobRun.job_name == "settlement_rebuild")) is None
        assert session.get(SettlementMonthClose, MONTH) is None

    monkeypatch.setattr(close, "_calculation_inputs_digest", original_digest)
    assert close.ensure_month_close_job(factory, now=NOW, bounded=True)


def test_background_snapshot_rechecks_published_days_after_preparing_evidence(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session)
    original = close._bounded_dispatch_session

    @contextmanager
    def republish_during_handoff(passed, *, deadline, snapshot):
        with original(passed, deadline=deadline, snapshot=snapshot) as session:
            yield session
        if not snapshot:
            with factory.begin() as session:
                revision = close.published_days_revisions(session, MONTH)[0]
                session.get(JobRun, revision.split("@", 1)[1]).status = "failed"

    monkeypatch.setattr(close, "_bounded_dispatch_session", republish_during_handoff)
    assert close.ensure_month_close_job(factory, now=NOW, bounded=True) is None
    with factory() as session:
        assert session.scalar(select(JobRun.job_id).where(JobRun.job_name == "settlement_rebuild")) is None


def test_background_keeps_an_already_certified_job_with_expiring_sessions(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    engine = bootstrap_session.get_bind()
    _seed(bootstrap_session)
    factory = sessionmaker(bind=engine, expire_on_commit=True, autoflush=False)
    with factory.begin() as session:
        qualification = close.freeze_month(session, MONTH, now=NOW)
        session.add(SettlementMonthClose(
            business_month=MONTH, source_input_sha256="a" * 64, source_job_id="already-certified",
            qualification_version_id=qualification.version_id,
            is_complete=True, blocked_store_ids=[], unscoped_issue_count=0,
        ))
    assert close.ensure_month_close_job(factory, now=NOW, bounded=True) == "already-certified"


def test_postgres_background_digest_is_consistent_without_account_capture_or_daily_claim_locks(
    postgres_engine, monkeypatch,
):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    with Session(postgres_engine, autoflush=False) as session:
        factory = _seed(session)
    first_id = close.ensure_month_close_job(factory, now=NOW, bounded=True)
    assert first_id
    original_digest = close._calculation_inputs_digest
    checked = []

    def check_snapshot(session, *args, **kwargs):
        assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        with factory.begin() as competing:
            # A different connection can still acquire the locks used to
            # capture account evidence and claim a daily source writer.
            for key in (7462180066, 661893198734880846):
                assert competing.scalar(select(func.pg_try_advisory_xact_lock(key)))
        checked.append(True)
        return original_digest(session, *args, **kwargs)

    monkeypatch.setattr(close, "_calculation_inputs_digest", check_snapshot)
    assert close.ensure_month_close_job(factory, now=NOW, bounded=True) == first_id
    assert checked == [True]


def test_postgres_background_does_not_repeat_a_scan_held_by_another_dispatcher(postgres_engine, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    with Session(postgres_engine, autoflush=False) as session:
        factory = _seed(session)
    with factory.begin() as blocker:
        assert close._try_discovery_lock(blocker)
        def unexpected_scan(*args, **kwargs):
            pytest.fail("another background dispatcher already owns the scan")

        with monkeypatch.context() as check:
            check.setattr(close, "_calculation_inputs_digest", unexpected_scan)
            assert close.ensure_month_close_job(factory, now=NOW, bounded=True) is None
    assert close.ensure_month_close_job(factory, now=NOW, bounded=True)
