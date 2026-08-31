from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import JobRun, JobStageRun
from apps.worker import stage_runner


def _factory(db_session: Session) -> sessionmaker[Session]:
    return sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)


def _seed_finalize_job(db_session: Session, job_id: str) -> None:
    db_session.add(
        JobRun(
            job_id=job_id,
            job_name="finalize",
            job_kind="finalize",
            status="running",
            current_stage="finalize",
            metadata_json={"required_stages": ["finalize"]},
        )
    )
    db_session.commit()


@dataclass
class _RecorderMutation:
    seen: list[tuple[str, str, str]]
    fail: bool = False
    mutate_stage: bool = False

    def apply(self, session: Session, *, job: JobRun, stage: JobStageRun) -> None:
        assert session.in_transaction()
        self.seen.append((job.job_id, stage.stage_run_id, stage.status))
        job.rows_written = 7
        if self.mutate_stage:
            stage.status = "cancelled"
        if self.fail:
            raise RuntimeError("mutation failed")


def test_isolated_typed_output_applies_mutation_before_runner_owned_stage_success(
    db_session: Session,
):
    _seed_finalize_job(db_session, "typed-finalize")
    seen: list[tuple[str, str, str]] = []
    mutation = _RecorderMutation(seen)

    def handler(_session: Session, _job: JobRun):
        assert hasattr(stage_runner, "StageHandlerOutput")
        return stage_runner.StageHandlerOutput(
            checkpoint={"generation_id": "generation-1"},
            before_success_commit=mutation,
        )

    handler.requires_independent_sessions = True
    result = stage_runner.run_daily_stages(
        _factory(db_session),
        job_id="typed-finalize",
        handlers={"finalize": handler},
        stage_order=("finalize",),
    )

    db_session.expire_all()
    stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == "typed-finalize",
            JobStageRun.stage_name == "finalize",
        )
    )
    assert result.completed_stages == ("finalize",)
    assert seen == [("typed-finalize", "stage-typed-finalize-finalize", "pending")]
    assert stage is not None
    assert stage.status == "success"
    assert stage.checkpoint_json["generation_id"] == "generation-1"
    assert db_session.get(JobRun, "typed-finalize").rows_written == 7


def test_mutation_failure_rolls_back_control_change_and_never_marks_stage_success(
    db_session: Session,
):
    _seed_finalize_job(db_session, "typed-failure")
    mutation = _RecorderMutation([], fail=True)

    def handler(_session: Session):
        return stage_runner.StageHandlerOutput(
            checkpoint={"generation_id": "generation-fail"},
            before_success_commit=mutation,
        )

    handler.requires_independent_sessions = True
    with pytest.raises(RuntimeError, match="mutation failed"):
        stage_runner.run_daily_stages(
            _factory(db_session),
            job_id="typed-failure",
            handlers={"finalize": handler},
            stage_order=("finalize",),
        )
    db_session.expire_all()
    job = db_session.get(JobRun, "typed-failure")
    stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == "typed-failure",
            JobStageRun.stage_name == "finalize",
        )
    )
    assert job.rows_written is None
    assert stage is not None and stage.status == "failed"
    assert stage.committed_at is None


def test_runner_rejects_mutation_that_writes_stage_owned_fields(db_session: Session):
    _seed_finalize_job(db_session, "typed-stage-owner")

    def handler(_session: Session):
        return stage_runner.StageHandlerOutput(
            checkpoint={},
            before_success_commit=_RecorderMutation([], mutate_stage=True),
        )

    handler.requires_independent_sessions = True
    with pytest.raises(RuntimeError, match="stage-owned"):
        stage_runner.run_daily_stages(
            _factory(db_session),
            job_id="typed-stage-owner",
            handlers={"finalize": handler},
            stage_order=("finalize",),
        )
