"""DYDATA-102 P1: the queued publication job must never displace a requester job.

``queue_job_run`` stamps ``started_at`` from ``utcnow()``, whose granularity on
Windows is coarse enough that two enqueues can share an identical timestamp.
The claim order used to fall through to ``job_id``, and because
``settlement-publication-after-...`` sorts after ``admin_...`` lexicographically,
the automatic publication row won the single execution slot and the
user-triggered rebuild was silently marked superseded.  These tests pin the
explicit tie-break so the behaviour cannot regress.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from apps.worker.repositories import queue_job_run
from apps.worker.settlement_rebuild import claim_latest_settlement_rebuild_job

TIE = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
PUBLICATION_JOB_ID = "settlement-publication-after-collect-1"
REQUESTER_JOB_ID = "admin_non_commission_owner_accounts-abc12345"


def _factory(session: Session) -> sessionmaker:
    return sessionmaker(
        bind=session.get_bind(), autoflush=False, autocommit=False, future=True
    )


def test_requester_job_wins_the_slot_when_enqueue_timestamps_tie(db_session):
    queue_job_run(
        db_session,
        PUBLICATION_JOB_ID,
        "settlement_rebuild",
        metadata_json={"source_run_id": "collect-1"},
        started_at=TIE,
    )
    queue_job_run(
        db_session,
        REQUESTER_JOB_ID,
        "settlement_rebuild",
        metadata_json={"trigger": "admin_non_commission_owner_accounts"},
        started_at=TIE,
    )
    db_session.commit()

    claimed = claim_latest_settlement_rebuild_job(_factory(db_session))

    assert claimed is not None
    assert claimed[0] == REQUESTER_JOB_ID


def test_newest_requester_job_still_wins_over_an_older_publication(db_session):
    queue_job_run(
        db_session,
        PUBLICATION_JOB_ID,
        "settlement_rebuild",
        metadata_json={"source_run_id": "collect-1"},
        started_at=TIE,
    )
    queue_job_run(
        db_session,
        REQUESTER_JOB_ID,
        "settlement_rebuild",
        metadata_json={"trigger": "admin_non_commission_owner_accounts"},
        started_at=TIE.replace(microsecond=1),
    )
    db_session.commit()

    claimed = claim_latest_settlement_rebuild_job(_factory(db_session))

    assert claimed is not None
    assert claimed[0] == REQUESTER_JOB_ID


def test_publication_job_is_still_claimed_when_it_is_the_only_work(db_session):
    queue_job_run(
        db_session,
        PUBLICATION_JOB_ID,
        "settlement_rebuild",
        metadata_json={"source_run_id": "collect-1"},
        started_at=TIE,
    )
    db_session.commit()

    claimed = claim_latest_settlement_rebuild_job(_factory(db_session))

    assert claimed is not None
    assert claimed[0] == PUBLICATION_JOB_ID
