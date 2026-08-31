from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    JobEvent,
    JobRun,
    JobStageRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
)
from apps.worker.daily_windows import enqueue_finalize_if_ready, plan_daily_sync
from apps.worker.stage_runner import run_daily_stages
from apps.worker.task_control import claim_job, complete_job

def _factory(session: Session) -> sessionmaker[Session]:
    return sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def _complete_prerequisites(
    session: Session,
    *,
    parent_job_id: str,
    changed: bool,
) -> None:
    now = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)
    children = list(
        session.scalars(
            select(JobRun)
            .where(JobRun.parent_job_id == parent_job_id, JobRun.job_kind == "date_sync")
            .order_by(JobRun.business_date, JobRun.job_id)
        )
    )
    for child in children:
        child.status = "success"
        summary = {
            "mode": "incremental",
            "completed": True,
            "impact_count": 0 if not changed else 1,
            "coupon_count": 0 if not changed else 1,
            "detail_count": 0 if not changed else 1,
            "result_count": 0 if not changed else 1,
            "adjustment_count": 0,
            "last_impact_id": None if not changed else 1,
            "affected_months": [] if not changed else [child.business_date.strftime("%Y-%m")],
            "affected_store_ids": [] if not changed else ["store-1"],
        }
        session.add(
            JobStageRun(
                stage_run_id=f"stage-{child.job_id}-settle",
                job_id=child.job_id,
                stage_name="settle",
                status="success",
                checkpoint_json={
                    "settlement_summary": summary,
                    "store_score_snapshot": {
                        "deferred": True,
                        "consumer": "T3.4.finalize",
                        "affected_store_ids": list(summary["affected_store_ids"]),
                        "rule_closure": "published-rules-and-eligible-stores",
                    },
                },
                lease_epoch=1,
                started_at=now,
                finished_at=now,
                committed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()


def _seed_base(session: Session) -> str:
    base_id = "finalize-e2e-base"
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


def test_publication_event_complete_job_and_promote_are_separate_transactions(
    db_session: Session,
) -> None:
    from apps.worker import finalize

    base_id = _seed_base(db_session)
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        target="settlement",
        requested_by="test",
        trigger_source="manual",
    )
    _complete_prerequisites(
        db_session,
        parent_job_id=plan.parent_job_id,
        changed=False,
    )
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
    factory = _factory(db_session)
    with factory() as session:
        fence = finalize.FenceToken.from_job(session.get(JobRun, job.job_id), token)

    def handler(_session: Session, _job: JobRun):
        return finalize.run_finalize_stage(
            factory,
            parent_job_id=plan.parent_job_id,
            fence_token=fence,
            batch_size=8,
        )

    handler.requires_independent_sessions = True
    stage_result = run_daily_stages(
        factory,
        job_id=job.job_id,
        handlers={"finalize": handler},
        stage_order=("finalize",),
        lease_owner=token.lease_owner,
        lease_epoch=token.lease_epoch,
        attempt_id=token.attempt_id,
        component_instance_id=token.component_instance_id,
    )
    assert stage_result.status == "success"

    with factory() as session:
        active_after_publish = session.get(SettlementProjectionActive, "settlement")
        assert active_after_publish is not None
        assert active_after_publish.generation_id != base_id
        finalize_job = session.get(JobRun, job.job_id)
        parent = session.get(JobRun, plan.parent_job_id)
        assert finalize_job is not None and finalize_job.status == "running"
        assert parent is not None and parent.status != "success"
        event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == job.job_id,
                JobEvent.event_type == "settlement_projection_published",
            )
        )
        child_stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == job.job_id,
                JobStageRun.stage_name == "finalize",
            )
        )
        assert event is not None and child_stage is not None
        assert event.stage_run_id == child_stage.stage_run_id

    with factory() as session:
        assert complete_job(session, token, success_count=1) is True
        session.commit()

    with factory() as session:
        assert session.get(JobRun, job.job_id).status == "success"
        assert session.get(JobRun, plan.parent_job_id).status == "success"
        parent_stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == plan.parent_job_id,
                JobStageRun.stage_name == "finalize",
            )
        )
        assert parent_stage is not None and parent_stage.status == "success"
        assert finalize.promote_range_parent_if_ready(session, plan.parent_job_id) is True
