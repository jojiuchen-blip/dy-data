"""Collection admission must leave complete static heads available."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import Base, JobRun
from apps.worker import priority_scheduler as priority
from apps.worker.publication_priority import priority_sync_pending
from apps.worker.repositories import parent_sync_gate_allows_claim

NOW = datetime.fromisoformat("2026-11-27T09:00:00+08:00")


@pytest.fixture()
def factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def daily_plan(factory):
    with factory.begin() as session:
        plan = priority.ensure_daily_priority_plan(session, NOW.date() - timedelta(days=1), now=NOW)
    return plan


def test_required_daily_yields_without_writes_or_row_locks(factory):
    daily_plan(factory)
    statements = []
    with factory() as session:
        def capture(conn, clause, *args):
            statements.append(str(clause.compile(dialect=postgresql.dialect())))
        event.listen(session.get_bind(), "before_execute", capture)
        try:
            assert priority_sync_pending(session, now=NOW)
            assert not session.new and not session.dirty and not session.deleted
        finally:
            event.remove(session.get_bind(), "before_execute", capture)
    assert statements and all(sql.lstrip().startswith("SELECT") for sql in statements)
    assert all("FOR UPDATE" not in sql and "FOR SHARE" not in sql for sql in statements)


@pytest.mark.parametrize("change", ["paused", "cancelled", "exhausted", "future_retry", "failed", "malformed", "history"])
def test_unclaimable_daily_does_not_starve_static_publications(factory, change):
    plan = daily_plan(factory)
    with factory.begin() as session:
        rows = list(session.scalars(select(JobRun).where(JobRun.parent_job_id == plan.parent_job_id)))
        for row in rows:
            if change == "paused":
                row.pause_after_stage_requested_at = NOW
            elif change == "cancelled":
                row.cancel_requested_at = NOW
            elif change == "exhausted":
                row.attempt_count = row.max_attempts
            elif change == "future_retry":
                row.status, row.next_retry_at = "retry_wait", NOW + timedelta(hours=1)
            elif change == "failed":
                row.status = "failed"
            elif change == "malformed":
                row.metadata_json = {**row.metadata_json, "target": "unknown"}
            elif change == "history":
                row.metadata_json = {**row.metadata_json, "priority_purpose": "history"}
    with factory() as session:
        assert not priority_sync_pending(session, now=NOW)


def test_due_retry_and_today_dimensions_yield_before_cutoff(factory):
    before_cutoff = NOW.replace(hour=1)
    with factory.begin() as session:
        priority._plan_due_dimensions(session, before_cutoff)
        rows = list(session.scalars(select(JobRun).where(JobRun.job_kind == "parent_sync")))
        for row in rows:
            row.status, row.next_retry_at = "retry_wait", before_cutoff - timedelta(seconds=1)
            row.started_at = before_cutoff
    with factory() as session:
        assert priority_sync_pending(session, now=before_cutoff)
        assert not priority_sync_pending(session, now=before_cutoff + timedelta(days=1))


def test_date_requires_successful_parent_and_probe_preserves_default_locks(factory):
    plan = daily_plan(factory)
    with factory() as session:
        child = session.scalar(select(JobRun).where(JobRun.parent_job_id == plan.parent_job_id,
                                                   JobRun.job_kind == "date_sync"))
        assert not parent_sync_gate_allows_claim(session, child, lock=False)
    with factory.begin() as session:
        parent = session.scalar(select(JobRun).where(JobRun.parent_job_id == plan.parent_job_id,
                                                    JobRun.job_kind == "parent_sync"))
        parent.status = "success"
    statements = []
    with factory() as session:
        def capture(conn, clause, *args):
            statements.append(str(clause.compile(dialect=postgresql.dialect())))
        event.listen(session.get_bind(), "before_execute", capture)
        try:
            assert priority_sync_pending(session, now=NOW)
            assert all("FOR UPDATE" not in sql for sql in statements)
            child = session.scalar(select(JobRun).where(JobRun.parent_job_id == plan.parent_job_id,
                                                       JobRun.job_kind == "date_sync"))
            statements.clear()
            assert parent_sync_gate_allows_claim(session, child)
            assert any("FOR UPDATE" in sql for sql in statements)
        finally:
            event.remove(session.get_bind(), "before_execute", capture)


def test_known_quota_cooldown_does_not_reserve_publication_window(factory, monkeypatch):
    from apps.worker import publication_priority
    daily_plan(factory)
    monkeypatch.setattr(publication_priority, "heavy_sync_rate_limit_cooldown_active", lambda _: True)
    with factory() as session:
        assert not priority_sync_pending(session, now=NOW)


def test_cancelled_dimension_parent_and_future_registration_do_not_reserve_a_slot(factory):
    with factory.begin() as session:
        priority._plan_due_dimensions(session, NOW)
        rows = list(session.scalars(select(JobRun)))
        for row in rows:
            if row.job_kind == "range_sync":
                row.cancel_requested_at = NOW
    with factory() as session:
        assert not priority_sync_pending(session, now=NOW)
    with factory.begin() as session:
        for row in session.scalars(select(JobRun)):
            row.cancel_requested_at = None
            row.started_at = NOW + timedelta(hours=1)
    with factory() as session:
        assert not priority_sync_pending(session, now=NOW)


def test_old_day_pending_cannot_keep_publications_waiting(factory):
    with factory.begin() as session:
        priority.ensure_daily_priority_plan(session, NOW.date() - timedelta(days=2), now=NOW - timedelta(days=1))
    with factory() as session:
        assert not priority_sync_pending(session, now=NOW)
