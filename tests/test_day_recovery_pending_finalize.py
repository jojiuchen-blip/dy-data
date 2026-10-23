"""Original pending day roots stopped only by an exhausted finalize."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import JobAttempt, JobRun
from apps.worker import day_recovery
from apps.worker.daily_windows import DailySyncPlan, enqueue_finalize_if_ready, plan_daily_sync
from apps.worker.task_control import claim_job
from test_worker_daily_orchestrator import _complete_finalize_prerequisites

NOW = datetime(2026, 10, 23, 2, tzinfo=UTC)


def _finish_attempt(session: Session, job: JobRun, *, failed: bool) -> None:
    token = claim_job(
        session,
        job_id=job.job_id,
        lease_owner="pending-finalize-test",
        component_instance_id="pending-finalize-worker",
        lease_seconds=60,
    )
    assert token is not None
    attempt = session.get(JobAttempt, token.attempt_id)
    attempt.finished_at = attempt.started_at + timedelta(seconds=1)
    attempt.exit_type = "fatal_failure" if failed else "success"
    attempt.exit_code = 1 if failed else 0
    job.status = "retry_wait" if failed else "success"
    job.next_retry_at = None
    job.lease_owner = None
    job.lease_expires_at = None
    session.flush()


def _stopped_root(session: Session) -> tuple[JobRun, dict[str, JobRun]]:
    plan = plan_daily_sync(
        session,
        start=date(2026, 8, 16),
        end=date(2026, 8, 17),
        target="all",
        requested_by="pending-finalize-test",
        trigger_source="history",
        config_version=day_recovery.PRIORITY_CONFIG_VERSION,
    )
    root = session.get(JobRun, plan.parent_job_id)
    children = {
        child.job_kind: child
        for child in session.scalars(
            select(JobRun).where(JobRun.parent_job_id == root.job_id)
        )
    }
    _complete_finalize_prerequisites(session, plan)
    children["date_sync"].status = "pending"
    session.flush()
    for kind in ("parent_sync", "date_sync"):
        _finish_attempt(session, children[kind], failed=False)
    finalize = enqueue_finalize_if_ready(session, root.job_id)
    assert finalize is not None
    for _ in range(3):
        _finish_attempt(session, finalize, failed=True)
    finalize.status = "failed"
    finalize.error_summary = "base settlement lineage depth exceeds sparse limit"
    children["finalize"] = finalize
    assert root.status == "pending"
    session.commit()
    return root, children


def _recover(
    session: Session, root: JobRun, key: str = "pending-finalize-v1"
) -> tuple[DailySyncPlan, bool]:
    return day_recovery.plan_day_recovery(
        session,
        parent=root,
        request_key=key,
        reason="collection completed; finalize exhausted",
        actor="system-admin",
        now=NOW,
    )


def test_original_pending_finalize_creates_generation_without_rewriting_evidence(
    db_session: Session,
) -> None:
    root, children = _stopped_root(db_session)
    original_ids = [root.job_id, *(child.job_id for child in children.values())]
    attempts_before = [
        (row.attempt_id, row.job_id, row.attempt_number, row.lease_epoch, row.exit_type)
        for row in db_session.scalars(select(JobAttempt).order_by(JobAttempt.attempt_id))
    ]
    rows_before = {
        row.job_id: (row.status, row.attempt_count, row.error_summary, row.lease_epoch)
        for row in [root, *children.values()]
    }
    plan, replayed = _recover(db_session, root)
    db_session.commit()
    db_session.expire_all()
    recovered = db_session.get(JobRun, plan.parent_job_id)
    assert replayed is False
    assert recovered.job_id not in original_ids
    assert recovered.metadata_json[day_recovery.RECOVERY_ROOT_KEY] == root.job_id
    assert day_recovery.generation_ordinal(recovered) == 1
    assert day_recovery.recovery_generations(root)[0]["parent_job_id"] == recovered.job_id
    for job_id, before in rows_before.items():
        row = db_session.get(JobRun, job_id)
        assert (row.status, row.attempt_count, row.error_summary, row.lease_epoch) == before
    assert [
        (row.attempt_id, row.job_id, row.attempt_number, row.lease_epoch, row.exit_type)
        for row in db_session.scalars(select(JobAttempt).order_by(JobAttempt.attempt_id))
    ] == attempts_before
    again, replayed = _recover(db_session, root)
    assert replayed is True
    assert again.parent_job_id == recovered.job_id
    assert len(day_recovery.recovery_generations(root)) == 1
    assert all(
        row.attempt_count == 0
        for row in db_session.scalars(
            select(JobRun).where(JobRun.parent_job_id == recovered.job_id)
        )
    )


@pytest.mark.parametrize("job_kind", ["root", "parent_sync", "date_sync", "finalize"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("lease_expires_at", NOW + timedelta(hours=1)),
        ("cancel_requested_at", NOW),
        ("pause_after_stage_requested_at", NOW),
    ],
)
def test_pending_finalize_respects_every_job_control(
    db_session: Session, job_kind: str, field: str, value: datetime
) -> None:
    root, children = _stopped_root(db_session)
    setattr(root if job_kind == "root" else children[job_kind], field, value)
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed):
        _recover(db_session, root)
    assert day_recovery.recovery_generations(root) == []


@pytest.mark.parametrize("job_kind", ["root", "parent_sync", "date_sync", "finalize"])
def test_pending_finalize_rejects_unfinished_attempt(
    db_session: Session, job_kind: str
) -> None:
    root, children = _stopped_root(db_session)
    job = root if job_kind == "root" else children[job_kind]
    db_session.add(
        JobAttempt(
            attempt_id="open-attempt",
            job_id=job.job_id,
            attempt_number=4,
            lease_epoch=4,
            component_instance_id="pending-finalize-worker",
            component_type="worker",
            started_at=NOW,
            finished_at=None,
        )
    )
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed):
        _recover(db_session, root)


@pytest.mark.parametrize("attempts,quota,allowed", [(2, 0, False), (3, 1, False), (4, 1, True)])
def test_pending_finalize_uses_quota_adjusted_attempt_budget(
    db_session: Session, attempts: int, quota: int, allowed: bool
) -> None:
    root, children = _stopped_root(db_session)
    children["finalize"].attempt_count = attempts
    children["finalize"].quota_pause_count = quota
    db_session.commit()
    if allowed:
        assert _recover(db_session, root)[1] is False
    else:
        with pytest.raises(day_recovery.DayRecoveryNotAllowed):
            _recover(db_session, root)


@pytest.mark.parametrize("job_kind", ["parent_sync", "date_sync", "finalize"])
@pytest.mark.parametrize("status", ["pending", "retry_wait", "running", "cancelled"])
def test_pending_finalize_rejects_runnable_or_cancelled_children(
    db_session: Session, job_kind: str, status: str
) -> None:
    root, children = _stopped_root(db_session)
    children[job_kind].status = status
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed):
        _recover(db_session, root)


@pytest.mark.parametrize("job_kind", ["parent_sync", "date_sync", "finalize", "product_sync"])
def test_pending_finalize_rejects_extra_children(db_session: Session, job_kind: str) -> None:
    root, _ = _stopped_root(db_session)
    db_session.add(
        JobRun(
            job_id="unexpected-child",
            job_name=job_kind,
            job_kind=job_kind,
            parent_job_id=root.job_id,
            status="success",
            execution_slot="heavy_sync",
            business_date=date(2026, 8, 16) if job_kind == "date_sync" else None,
            window_start=root.window_start,
            window_end=root.window_end,
            data_source=root.data_source,
            config_version="unexpected-config",
        )
    )
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed):
        _recover(db_session, root)


@pytest.mark.parametrize("job_kind", ["parent_sync", "date_sync", "finalize"])
@pytest.mark.parametrize("field", ["config_version", "data_source", "window_start", "window_end"])
def test_pending_finalize_rejects_child_input_mismatch(
    db_session: Session, job_kind: str, field: str
) -> None:
    root, children = _stopped_root(db_session)
    job = children[job_kind]
    value = getattr(job, field)
    setattr(job, field, value + timedelta(hours=1) if field.startswith("window") else "other")
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed):
        _recover(db_session, root)


def test_pending_finalize_keeps_in_flight_and_two_generation_limits(db_session: Session) -> None:
    root, _ = _stopped_root(db_session)
    first, _ = _recover(db_session, root)
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="in flight"):
        _recover(db_session, root, "pending-finalize-v2")
    first_root = db_session.get(JobRun, first.parent_job_id)
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="cannot itself"):
        _recover(db_session, first_root, "self-recovery")
    first_root.status = "failed"
    db_session.commit()
    second, _ = _recover(db_session, root, "pending-finalize-v2")
    db_session.get(JobRun, second.parent_job_id).status = "failed"
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="budget exhausted"):
        _recover(db_session, root, "pending-finalize-v3")
    assert [entry["ordinal"] for entry in day_recovery.recovery_generations(root)] == [1, 2]


@pytest.mark.parametrize("job_kind", ["parent_sync", "date_sync", "finalize"])
def test_pending_finalize_rejects_missing_collection_or_finalize(
    db_session: Session, job_kind: str
) -> None:
    root, children = _stopped_root(db_session)
    # Preserve attempts and stages while taking the required child out of the shape.
    children[job_kind].job_kind = "product_sync"
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed):
        _recover(db_session, root)


def test_pending_finalize_rejects_mismatched_business_date(db_session: Session) -> None:
    root, children = _stopped_root(db_session)
    children["date_sync"].business_date = date(2026, 8, 15)
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed):
        _recover(db_session, root)


def test_pending_finalize_does_not_recover_a_published_day(db_session: Session) -> None:
    root, children = _stopped_root(db_session)
    children["finalize"].status = "success"
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed):
        _recover(db_session, root)
    root.status = "success"
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="not terminal"):
        _recover(db_session, root)


def test_pending_finalize_rejects_key_already_bound_to_another_root(db_session: Session) -> None:
    root, _ = _stopped_root(db_session)
    collision = plan_daily_sync(
        db_session,
        start=date(2026, 8, 16),
        end=date(2026, 8, 17),
        target="all",
        requested_by="other-recovery",
        trigger_source="recovery",
        data_source=root.data_source,
        config_version=day_recovery.recovery_config_version("pending-finalize-v1"),
    )
    other = db_session.get(JobRun, collision.parent_job_id)
    other.metadata_json = {
        **other.metadata_json,
        day_recovery.RECOVERY_ROOT_KEY: "another-original-root",
    }
    db_session.commit()
    with pytest.raises(day_recovery.DayRecoveryNotAllowed, match="another day plan"):
        _recover(db_session, root)
    assert day_recovery.recovery_generations(root) == []
