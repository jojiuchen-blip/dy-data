"""DYDATA-102: only a *successful* settlement may enqueue a publication job.

The queueing hook must stay idempotent per trigger and must never schedule
billing publication after a settlement that raised or reported failures.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from apps.api.dy_api.models import JobRun
from apps.worker import pipeline
from apps.worker import settlement as settlement_mod
from apps.worker.collectors.types import CollectionWindow, PhaseStats
from apps.worker.settlement import SettlementStats

WINDOW = CollectionWindow(
    start=datetime(2026, 9, 1, tzinfo=timezone.utc),
    end=datetime(2026, 9, 2, tzinfo=timezone.utc),
    timezone_name="Asia/Shanghai",
)
EMPTY_STATS = SettlementStats(
    detail_count=0, issue_count=0, ranking_count=0, monthly_count=0
)


def _publication_ids(session) -> list[str]:
    return list(
        session.scalars(
            select(JobRun.job_id).where(
                JobRun.job_id.like("settlement-publication-after-%")
            )
        )
    )


def test_successful_settlement_job_enqueues_publication_once(db_session, monkeypatch):
    monkeypatch.setattr(
        settlement_mod, "rebuild_settlement", lambda session, **kwargs: EMPTY_STATS
    )

    settlement_mod.run_settlement_job(
        db_session, job_id="settle-ok", source_run_id="settle-ok"
    )
    settlement_mod.run_settlement_job(
        db_session, job_id="settle-ok", source_run_id="settle-ok"
    )

    assert _publication_ids(db_session) == ["settlement-publication-after-settle-ok"]
    publication = db_session.get(JobRun, "settlement-publication-after-settle-ok")
    assert publication is not None
    assert publication.status == "queued"
    assert publication.metadata_json["trigger_source"] == "settlement_job_completed"


def test_failed_settlement_job_enqueues_nothing(db_session, monkeypatch):
    def _boom(session, **kwargs):
        raise RuntimeError("settlement rebuild failed")

    monkeypatch.setattr(settlement_mod, "rebuild_settlement", _boom)

    with pytest.raises(RuntimeError):
        settlement_mod.run_settlement_job(
            db_session, job_id="settle-fail", source_run_id="settle-fail"
        )

    assert _publication_ids(db_session) == []
    job = db_session.get(JobRun, "settle-fail")
    assert job is not None and job.status == "failed"


def test_pipeline_enqueues_once_on_success(db_session):
    runner = lambda session, source_run_id: PhaseStats(name="settlement", upserted=2)

    for _ in range(2):
        pipeline.run_collect_and_settle(
            db_session,
            client=object(),
            window=WINDOW,
            job_id="collect-ok",
            include_browser_export=False,
            collectors=[],
            settlement_runner=runner,
        )

    assert _publication_ids(db_session) == [
        "settlement-publication-after-collect-ok"
    ]
    publication = db_session.get(JobRun, "settlement-publication-after-collect-ok")
    assert publication.metadata_json["trigger_source"] == "collect_and_settle_completed"


def test_pipeline_does_not_enqueue_when_the_settlement_phase_raises(db_session):
    def _boom(session, source_run_id):
        raise RuntimeError("settlement phase failed")

    with pytest.raises(RuntimeError):
        pipeline.run_collect_and_settle(
            db_session,
            client=object(),
            window=WINDOW,
            job_id="collect-fail",
            include_browser_export=False,
            collectors=[],
            settlement_runner=_boom,
        )

    assert _publication_ids(db_session) == []
    job = db_session.get(JobRun, "collect-fail")
    assert job is not None and job.status == "failed"


def test_pipeline_does_not_enqueue_when_the_phase_reports_failures(db_session):
    runner = lambda session, source_run_id: PhaseStats(name="settlement", failed=3)

    pipeline.run_collect_and_settle(
        db_session,
        client=object(),
        window=WINDOW,
        job_id="collect-partial",
        include_browser_export=False,
        collectors=[],
        settlement_runner=runner,
    )

    assert _publication_ids(db_session) == []
