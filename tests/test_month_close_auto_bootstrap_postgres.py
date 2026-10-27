"""PostgreSQL qualification bootstrap, exact input hashing and dispatch fencing."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobRun
from apps.worker import month_close as close
from test_protected_billing_authority_postgres import postgres_engine  # noqa: F401
from test_month_close_auto_bootstrap import (
    NOW, _seed,
    test_freeze_automatically_bootstraps_whole_month_actual_rebuild_and_publication as automatic,
    test_unapproved_old_current_fees_block_commit_and_publication as rejected,
    test_full_runner_without_active_pointer_rolls_back_unpinned_october_economics as rejected_full,
)


@pytest.mark.parametrize("legacy", (False, True))
def test_postgres_automatic_bootstrap_rebuilds_and_publishes_real_full_month(postgres_engine, monkeypatch, legacy):
    with Session(postgres_engine, autoflush=False) as session:
        automatic(session, legacy, monkeypatch)


def test_postgres_concurrent_ticks_share_frozen_input_job_without_resetting_attempts(postgres_engine):
    with Session(postgres_engine, autoflush=False) as session:
        factory = _seed(session, legacy=True)
    barrier = Barrier(2)
    def tick(_):
        barrier.wait(timeout=5)
        return close.ensure_month_close_job(factory, now=NOW)
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(executor.map(tick, range(2)))
    assert jobs[0] == jobs[1] and jobs[0]
    with factory.begin() as session:
        job = session.get(JobRun, jobs[0])
        job.status, job.attempt_count, job.max_attempts = "failed", 3, 3
    assert close.ensure_month_close_job(factory, now=NOW) == jobs[0]
    with factory() as session:
        assert session.get(JobRun, jobs[0]).attempt_count == 3
        assert session.scalar(select(func.count()).select_from(JobRun).where(JobRun.job_name == "settlement_rebuild")) == 1


def test_postgres_unqualified_legacy_current_rolls_back_month_economics(postgres_engine):
    with Session(postgres_engine, autoflush=False) as session:
        rejected(session, "unknown")


def test_postgres_full_without_active_rolls_back_unknown_october_aggregates(postgres_engine, monkeypatch):
    with Session(postgres_engine, autoflush=False) as session:
        rejected_full(session, True, monkeypatch)
