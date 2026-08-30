from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    ClueAllocationRule,
    ClueAllocationRuleVersion,
    JobEvent,
    JobRun,
    JobStageRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
)
from apps.worker.daily_windows import enqueue_finalize_if_ready, plan_daily_sync
from apps.worker.task_control import claim_job


def _factory(session: Session) -> sessionmaker[Session]:
    return sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def _seed_base(session: Session, prefix: str) -> str:
    base_id = f"{prefix}-base"
    session.add(
        SettlementProjectionGeneration(
            generation_id=base_id,
            base_generation_id=None,
            generation_kind="legacy_root",
            compaction_base_generation_id=None,
            projection_name="settlement",
            state="published",
            input_fingerprint="0" * 64,
            lineage_depth=0,
            estimated_write_rows=0,
            estimated_write_bytes=0,
            estimated_wal_bytes=0,
            estimated_disk_headroom_bytes=0,
            checkpoint_json={"phase": "published"},
            last_key=None,
            manifest_checksum="1" * 64,
            source_input_json={},
            published_at=datetime.now(UTC),
        )
    )
    session.add(
        SettlementProjectionActive(
            projection_name="settlement",
            generation_id=base_id,
        )
    )
    session.flush()
    return base_id


def _settle_checkpoint(*, day: date, changed: bool = True) -> dict[str, object]:
    month = day.strftime("%Y-%m")
    store_id = f"store-{day.isoformat()}"
    return {
        "settlement_summary": {
            "mode": "incremental",
            "completed": True,
            "impact_count": 1 if changed else 0,
            "coupon_count": 1 if changed else 0,
            "detail_count": 1 if changed else 0,
            "result_count": 1 if changed else 0,
            "adjustment_count": 0,
            "last_impact_id": 100 + day.day if changed else None,
            "affected_months": [month] if changed else [],
            "affected_store_ids": [store_id] if changed else [],
        },
        "store_score_snapshot": {
            "deferred": True,
            "consumer": "T3.4.finalize",
            "affected_store_ids": [store_id] if changed else [],
            "rule_closure": "published-rules-and-eligible-stores",
        },
    }


def _complete_prerequisites(
    session: Session,
    *,
    parent_job_id: str,
    changed: bool = True,
) -> None:
    now = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)
    parent = session.get(JobRun, parent_job_id)
    assert parent is not None
    parent_stage = session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    if parent_stage is not None:
        parent_stage.status = "success"
        parent_stage.committed_at = now
        parent_stage.finished_at = now
    children = list(
        session.scalars(
            select(JobRun)
            .where(JobRun.parent_job_id == parent_job_id, JobRun.job_kind == "date_sync")
            .order_by(JobRun.business_date, JobRun.job_id)
        )
    )
    for child in children:
        child.status = "success"
        required = tuple((child.metadata_json or {}).get("required_stages") or ())
        for stage_name in required:
            checkpoint = (
                _settle_checkpoint(day=child.business_date, changed=changed)
                if stage_name == "settle"
                else {}
            )
            session.add(
                JobStageRun(
                    stage_run_id=f"stage-{child.job_id}-{stage_name}",
                    job_id=child.job_id,
                    stage_name=stage_name,
                    status="success",
                    checkpoint_json=checkpoint,
                    lease_epoch=1,
                    started_at=now,
                    finished_at=now,
                    committed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
    session.flush()


@pytest.mark.parametrize(
    ("target", "expected"),
    [("all", True), ("settlement", True), ("clue_center", False), ("backend_aweme_export", False)],
)
def test_finalize_matrix_and_required_stages(
    db_session: Session,
    target: str,
    expected: bool,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        target=target,
        requested_by="test",
        trigger_source="manual",
    )
    if plan.daily_jobs:
        _complete_prerequisites(db_session, parent_job_id=plan.parent_job_id)
    else:
        parent_stage = db_session.scalar(
            select(JobStageRun).where(JobStageRun.job_id == plan.parent_job_id)
        )
        if parent_stage is not None:
            parent_stage.status = "success"
            parent_stage.committed_at = datetime.now(UTC)
    job = enqueue_finalize_if_ready(db_session, plan.parent_job_id)
    assert (job is not None) is expected
    if not expected:
        assert db_session.scalar(
            select(func.count()).select_from(JobRun).where(JobRun.job_kind == "finalize")
        ) == 0
        return
    assert job is not None
    assert job.metadata_json["required_stages"] == ["finalize"]
    assert job.metadata_json["target"] == target
    assert job.metadata_json["settle_stage_fences"]
    assert db_session.scalar(
        select(func.count()).select_from(JobStageRun).where(
            JobStageRun.job_id == job.job_id,
            JobStageRun.stage_name == "finalize",
        )
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(JobEvent).where(JobEvent.job_id == job.job_id)
    ) == 0


def test_fence_token_uses_only_committed_settlement_summary_and_store_score_snapshot(
    db_session: Session,
) -> None:
    from apps.worker import finalize

    _seed_base(db_session, "validate-finalize")
    db_session.add(
        ClueAllocationRule(
            rule_id="validate-finalize-rule",
            rule_name="Validate finalize rule",
            scope_type="global",
            scope_key="validate-finalize-global",
        )
    )
    db_session.flush()
    db_session.add(
        ClueAllocationRuleVersion(
            rule_version_id="validate-finalize-rule-v1",
            rule_id="validate-finalize-rule",
            version_no=1,
            status="published",
            published_at=datetime.now(UTC),
        )
    )
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 3),
        target="settlement",
        requested_by="test",
        trigger_source="manual",
    )
    _complete_prerequisites(db_session, parent_job_id=plan.parent_job_id)
    job = enqueue_finalize_if_ready(db_session, plan.parent_job_id)
    assert job is not None
    token = claim_job(
        db_session,
        job_id=job.job_id,
        lease_owner="finalize-owner",
        component_instance_id="finalize-component",
        lease_seconds=120,
    )
    assert token is not None
    db_session.commit()
    db_session.expire_all()
    fence = finalize.FenceToken.from_job(db_session.get(JobRun, job.job_id), token)
    result = finalize.validate_finalize_input(db_session, plan.parent_job_id, fence)
    assert result.parent_job_id == plan.parent_job_id
    assert result.finalize_job_id == job.job_id
    assert result.affected_months == ("2026-08",)
    assert result.affected_store_ids == ("store-2026-08-01", "store-2026-08-02")
    assert result.snapshot_date == date(2026, 8, 2)
    assert len(result.input_fingerprint) == 64

    settle = db_session.scalar(
        select(JobStageRun)
        .where(JobStageRun.job_id == plan.daily_jobs[0].job_id, JobStageRun.stage_name == "settle")
    )
    assert settle is not None
    settle.committed_at = datetime(2026, 8, 9, 2, 0, tzinfo=UTC)
    db_session.flush()
    with pytest.raises(RuntimeError, match="fence"):
        finalize.validate_finalize_input(db_session, plan.parent_job_id, fence)


def test_finalize_job_is_claimable_on_sqlite(db_session: Session) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        target="settlement",
        requested_by="test",
        trigger_source="manual",
    )
    _complete_prerequisites(db_session, parent_job_id=plan.parent_job_id)
    job = enqueue_finalize_if_ready(db_session, plan.parent_job_id)
    assert job is not None
    token = claim_job(
        db_session,
        job_id=job.job_id,
        lease_owner="owner",
        component_instance_id="component",
        lease_seconds=120,
    )
    assert token is not None
    assert token.current_stage == "finalize"


def test_finalize_daily_task_uses_explicit_stage_order(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.worker import daily_task
    from apps.worker.stage_runner import DailyStageResult

    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        target="settlement",
        requested_by="test",
        trigger_source="manual",
    )
    _complete_prerequisites(db_session, parent_job_id=plan.parent_job_id)
    job = enqueue_finalize_if_ready(db_session, plan.parent_job_id)
    assert job is not None
    token = claim_job(
        db_session,
        job_id=job.job_id,
        lease_owner="owner",
        component_instance_id="component",
        lease_seconds=120,
    )
    assert token is not None
    db_session.commit()
    monkeypatch.setenv("DY_WORKER_LEASE_OWNER", token.lease_owner)
    monkeypatch.setenv("DY_WORKER_LEASE_EPOCH", str(token.lease_epoch))
    monkeypatch.setenv("DY_WORKER_ATTEMPT_ID", token.attempt_id)
    monkeypatch.setenv("DY_WORKER_COMPONENT_ID", token.component_instance_id)
    observed: dict[str, object] = {}

    def fake_runner(_factory, **kwargs):
        observed.update(kwargs)
        return DailyStageResult(job_id=job.job_id, status="success")

    monkeypatch.setattr(daily_task, "run_daily_stages", fake_runner)
    result = daily_task.execute_daily_task(
        job.job_id,
        session_factory=_factory(db_session),
        handlers={"finalize": lambda _session, _job: {}},
    )
    assert result.status == "success"
    assert observed["stage_order"] == ("finalize",)
    assert tuple(observed["handlers"]) == ("finalize",)


def test_finalize_reuse_pending_identity_without_prewriting_once_event(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        target="settlement",
        requested_by="test",
        trigger_source="manual",
    )
    _complete_prerequisites(db_session, parent_job_id=plan.parent_job_id)
    first = enqueue_finalize_if_ready(db_session, plan.parent_job_id)
    assert first is not None
    first.metadata_json = {"parent_job_id": plan.parent_job_id}
    db_session.flush()

    replay = enqueue_finalize_if_ready(db_session, plan.parent_job_id)
    assert replay is not None and replay.job_id == first.job_id
    assert replay.metadata_json["required_stages"] == ["finalize"]
    assert db_session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.job_kind == "finalize")
    ) == 1
    assert db_session.scalar(select(func.count()).select_from(JobEvent)) == 0
