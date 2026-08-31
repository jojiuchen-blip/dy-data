from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    JobEvent,
    JobRun,
    JobStageRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
)


def _seed_publish(db_session: Session, *, prefix: str) -> tuple[JobRun, JobStageRun, str, str]:
    parent_id = f"{prefix}-parent"
    job_id = f"{prefix}-finalize"
    base_id = f"{prefix}-base"
    generation_id = f"{prefix}-generation"
    fingerprint = (prefix.encode().hex() + "a" * 64)[:64]
    db_session.add(
        JobRun(
            job_id=parent_id,
            job_name="range_sync",
            job_kind="range_sync",
            status="running",
            metadata_json={},
        )
    )
    db_session.flush()
    job = JobRun(
        job_id=job_id,
        job_name="finalize",
        job_kind="finalize",
        parent_job_id=parent_id,
        status="running",
        current_stage="finalize",
        lease_owner="worker-a",
        metadata_json={"required_stages": ["finalize"]},
    )
    stage = JobStageRun(
        stage_run_id=f"stage-{job_id}-finalize",
        job_id=job_id,
        stage_name="finalize",
        status="pending",
        checkpoint_json={},
    )
    db_session.add_all(
        [
            job,
            stage,
            SettlementProjectionGeneration(
                generation_id=base_id,
                generation_kind="legacy_root",
                projection_name="settlement",
                state="published",
                input_fingerprint="0" * 64,
                lineage_depth=0,
                checkpoint_json={},
                manifest_checksum="1" * 64,
                source_input_json={},
                published_at=datetime.now(timezone.utc),
            ),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            SettlementProjectionGeneration(
                generation_id=generation_id,
                base_generation_id=base_id,
                generation_kind="lineage",
                projection_name="settlement",
                state="ready",
                input_fingerprint=fingerprint,
                lineage_depth=1,
                checkpoint_json={"phase": "ready"},
                manifest_checksum="2" * 64,
                source_input_json={},
            ),
            SettlementProjectionActive(
                projection_name="settlement", generation_id=base_id
            ),
        ]
    )
    db_session.commit()
    return job, stage, generation_id, fingerprint


def test_projection_once_key_is_fixed_84_characters():
    from apps.worker import projection_publish

    key = projection_publish.projection_publish_once_key("", "a" * 64)
    assert key.startswith("finalize-consume-v1:")
    assert len(key) == 84
    assert key == projection_publish.projection_publish_once_key("", "a" * 64)
    assert key != projection_publish.projection_publish_once_key("p", "a" * 64)


def test_publish_mutation_updates_only_projection_and_once_event_in_caller_transaction(
    db_session: Session,
):
    from apps.worker import projection_publish

    job, stage, generation_id, fingerprint = _seed_publish(
        db_session, prefix="publish-success"
    )
    mutation = projection_publish.make_projection_publish_mutation(
        generation_id=generation_id,
        base_generation_id="publish-success-base",
        input_fingerprint=fingerprint,
        manifest_checksum="2" * 64,
        parent_job_id="publish-success-parent",
    )
    stage_before = (stage.status, dict(stage.checkpoint_json), stage.committed_at)
    mutation.apply(db_session, job=job, stage=stage)
    assert db_session.in_transaction()
    assert (stage.status, dict(stage.checkpoint_json), stage.committed_at) == stage_before
    db_session.commit()

    db_session.expire_all()
    generation = db_session.get(SettlementProjectionGeneration, generation_id)
    active = db_session.get(SettlementProjectionActive, "settlement")
    event = db_session.scalar(select(JobEvent))
    assert generation.state == "published"
    assert generation.published_at is not None
    assert active.generation_id == generation_id
    assert event.job_id == job.job_id
    assert event.stage_run_id == stage.stage_run_id
    assert len(event.idempotency_key) == 84
    assert event.payload_json == {
        "input_fingerprint": fingerprint,
        "generation_id": generation_id,
        "manifest_checksum": "2" * 64,
        "base_generation_id": "publish-success-base",
    }

    mutation.apply(db_session, job=job, stage=stage)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(JobEvent)) == 1


def test_publish_mismatch_fails_before_pointer_change(db_session: Session):
    from apps.worker import projection_publish

    job, stage, generation_id, fingerprint = _seed_publish(
        db_session, prefix="publish-mismatch"
    )
    mutation = projection_publish.make_projection_publish_mutation(
        generation_id=generation_id,
        base_generation_id="publish-mismatch-base",
        input_fingerprint=fingerprint,
        manifest_checksum="3" * 64,
        parent_job_id="publish-mismatch-parent",
    )
    db_session.begin()
    with pytest.raises(RuntimeError, match="manifest"):
        mutation.apply(db_session, job=job, stage=stage)
    db_session.rollback()
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == (
        "publish-mismatch-base"
    )
    assert db_session.get(SettlementProjectionGeneration, generation_id).state == "ready"
    assert db_session.scalar(select(func.count()).select_from(JobEvent)) == 0
