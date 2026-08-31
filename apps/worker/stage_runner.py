"""Short-session execution for one deterministic daily synchronization job.

The runner deliberately keeps stage work generic.  The caller supplies the
business handlers, while this module owns transaction boundaries, durable stage
checkpoints, and recovery from the first incomplete stage.
"""

from __future__ import annotations

import inspect
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Protocol, Sequence

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import JobAttempt, JobRun, JobStageRun
from apps.worker.pipeline import sanitize_error_message


STAGE_ORDER = ("collect", "materialize", "settle")
StageHandler = Callable[..., Any]


class BeforeSuccessCommit(Protocol):
    """A bounded control-plane mutation owned by the runner transaction."""

    def apply(
        self, session: Session, *, job: JobRun, stage: JobStageRun
    ) -> None: ...


@dataclass(frozen=True)
class StageHandlerOutput:
    checkpoint: Mapping[str, Any] = field(default_factory=dict)
    before_success_commit: BeforeSuccessCommit | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint, Mapping):
            raise TypeError("StageHandlerOutput.checkpoint must be a mapping")
        mutation = self.before_success_commit
        if mutation is not None and not callable(getattr(mutation, "apply", None)):
            raise TypeError("before_success_commit must provide apply()")


@dataclass(frozen=True)
class DailyStageResult:
    """Summary returned after all requested daily stages complete."""

    job_id: str
    status: str
    completed_stages: tuple[str, ...] = ()
    skipped_stages: tuple[str, ...] = ()
    failed_stage: str | None = None
    error_summary: str | None = None
    checkpoints: Mapping[str, dict[str, Any]] = field(default_factory=dict)


def run_daily_stages(
    session_factory: sessionmaker[Session] | Callable[[], Session],
    *,
    job_id: str,
    handlers: Mapping[str, StageHandler],
    control_session_factory: sessionmaker[Session] | Callable[[], Session] | None = None,
    after_stage_commit: Callable[[str], Any] | None = None,
    lease_owner: str | None = None,
    lease_epoch: int | None = None,
    attempt_id: str | None = None,
    component_instance_id: str | None = None,
    stage_order: Sequence[str] | None = None,
) -> DailyStageResult:
    """Run the required stages with one Session per stage.

    Non-isolated handlers keep their business writes and success checkpoint in
    the same stage Session and commit.  An isolated incremental handler owns
    independent short Sessions for its business batches; this stage Session is
    released before the handler runs and is reopened after it returns only for
    the final fenced control checkpoint and stage status.  Failure metadata is
    written by a new control Session after the business transaction has been
    rolled back.  Existing successful stages are observed from the control
    plane and never called again.
    """

    # Keep the legacy partial-handler convenience while allowing a parent
    # execution to be run directly with only its dimension stage.  The
    # explicit ``stage_order`` supplied by the daily entry point remains the
    # durable metadata authority whenever it is available.
    handler_stage_order = ("collect_dimensions", *STAGE_ORDER)
    required_order = tuple(
        stage_order
        or tuple(stage_name for stage_name in handler_stage_order if stage_name in handlers)
        or STAGE_ORDER
    )
    _validate_handlers(handlers, required_order)
    control_factory = control_session_factory or session_factory
    completed: list[str] = []
    skipped: list[str] = []
    checkpoints: dict[str, dict[str, Any]] = {}

    for stage_name in required_order:
        prior_status, _observed_current_stage = _read_stage_state(
            control_factory,
            job_id,
            stage_name,
        )
        if prior_status == "success":
            skipped.append(stage_name)
            continue

        stage_session = _new_session(session_factory)
        committed = False
        try:
            stage_session.begin()
            # Do not hold the JobRun row lock while the business handler is
            # running.  Heartbeat/timeout control must be able to update the
            # same row during a long collect/materialize/settle stage.
            job = stage_session.scalar(select(JobRun).where(JobRun.job_id == job_id))
            if job is None:
                raise ValueError(f"Unknown daily job: {job_id}")
            _assert_execution_lease(
                stage_session,
                job,
                lease_owner=lease_owner,
                lease_epoch=lease_epoch,
                attempt_id=attempt_id,
                component_instance_id=component_instance_id,
            )
            now = datetime.now(UTC)
            stage = stage_session.scalar(
                select(JobStageRun).where(
                    JobStageRun.job_id == job_id,
                    JobStageRun.stage_name == stage_name,
                )
            )

            isolated_handler = _handler_requires_independent_sessions(
                handlers[stage_name], job
            )
            if isolated_handler:
                # The incremental materializer owns page-level Sessions and
                # commits.  Release this stage Session's transaction before
                # entering it, then open a fresh transaction for the stage
                # checkpoint after the handler returns.
                stage_session.expunge(job)
                stage_session.rollback()
            output = _call_handler(handlers[stage_name], stage_session, job)
            if isolated_handler:
                stage_session.begin()
            checkpoint = _checkpoint_payload(output)
            mutation = (
                output.before_success_commit
                if isinstance(output, StageHandlerOutput)
                else None
            )
            # Re-lock and re-read the control row only for the short
            # checkpoint/commit window.  This is the pre-commit CAS: an
            # expired lease or a newer epoch rolls back both business writes
            # and the stage checkpoint.
            commit_job_statement = (
                select(JobRun)
                .where(JobRun.job_id == job_id)
                .execution_options(populate_existing=True)
            )
            if stage_session.get_bind().dialect.name == "postgresql":
                commit_job_statement = commit_job_statement.with_for_update()
            commit_job = stage_session.scalar(commit_job_statement)
            if commit_job is None:
                raise ValueError(f"Unknown daily job: {job_id}")
            _assert_execution_lease(
                stage_session,
                commit_job,
                lease_owner=lease_owner,
                lease_epoch=lease_epoch,
                attempt_id=attempt_id,
                component_instance_id=component_instance_id,
            )
            job = commit_job
            stage_statement = (
                select(JobStageRun)
                .where(
                    JobStageRun.job_id == job_id,
                    JobStageRun.stage_name == stage_name,
                )
                .execution_options(populate_existing=True)
            )
            if stage_session.get_bind().dialect.name == "postgresql":
                stage_statement = stage_statement.with_for_update()
            stage = stage_session.scalar(stage_statement)
            if stage is None:
                stage = JobStageRun(
                    stage_run_id=_stage_run_id(job_id, stage_name),
                    job_id=job_id,
                    stage_name=stage_name,
                    status="pending",
                    checkpoint_json={},
                    created_at=now,
                    updated_at=now,
                )
                stage_session.add(stage)
                stage_session.flush()
            if mutation is not None:
                _apply_before_success_commit(
                    stage_session,
                    mutation=mutation,
                    job=job,
                    stage=stage,
                )
            stage.lease_epoch = int(job.lease_epoch or 0)
            stage.started_at = stage.started_at or now
            finish_time = datetime.now(UTC)
            stage.checkpoint_json = {
                **(stage.checkpoint_json or {}),
                **checkpoint,
                "stage": stage_name,
                "status": "success",
            }
            stage.status = "success"
            stage.lease_epoch = int(job.lease_epoch or 0)
            stage.finished_at = finish_time
            stage.committed_at = finish_time
            stage.updated_at = finish_time
            next_stage = _next_stage_in(stage_name, required_order)
            job.current_stage = next_stage
            # Keep the heavy execution slot fenced for the whole child.  Even
            # after settle commits, ``complete_job`` must be the only path that
            # closes the JobRun/Attempt and releases the worker component.
            job.metadata_json = {
                **(job.metadata_json or {}),
                "stage_checkpoints": {
                    **((job.metadata_json or {}).get("stage_checkpoints") or {}),
                    stage_name: stage.checkpoint_json,
                },
            }
            if job.job_kind == "parent_sync" and job.parent_job_id:
                _promote_range_parent_stage(
                    stage_session,
                    parent_job_id=job.parent_job_id,
                    parent_execution_job_id=job.job_id,
                    required_stages=_required_stage_names(job),
                    checkpoint=stage.checkpoint_json,
                    now=finish_time,
                )
            stage_session.commit()
            committed = True
            completed.append(stage_name)
            checkpoints[stage_name] = dict(stage.checkpoint_json)
        except BaseException as exc:
            if not committed:
                try:
                    stage_session.rollback()
                except Exception:
                    pass
            stage_session.close()
            _record_stage_failure(
                control_factory,
                job_id=job_id,
                stage_name=stage_name,
                error=exc,
                lease_owner=lease_owner,
                lease_epoch=lease_epoch,
                attempt_id=attempt_id,
                component_instance_id=component_instance_id,
            )
            raise
        else:
            stage_session.close()

        if after_stage_commit is not None:
            # This hook models a process crash immediately after commit.  The
            # checkpoint is already durable, so a later invocation skips this
            # stage even when the hook raises.
            after_stage_commit(stage_name)

    return DailyStageResult(
        job_id=job_id,
        status="success",
        completed_stages=tuple(completed),
        skipped_stages=tuple(skipped),
        checkpoints=checkpoints,
    )


def _validate_handlers(
    handlers: Mapping[str, StageHandler],
    required_order: Sequence[str],
) -> None:
    unknown = set(handlers) - set(STAGE_ORDER)
    unknown -= {"collect_dimensions", "finalize"}
    if unknown:
        raise ValueError(f"Unknown daily stage(s): {', '.join(sorted(unknown))}")
    missing = set(required_order) - set(handlers)
    if missing:
        raise ValueError(f"Missing daily stage handler(s): {', '.join(sorted(missing))}")


def _new_session(factory: sessionmaker[Session] | Callable[[], Session]) -> Session:
    session = factory()
    if not isinstance(session, Session):
        raise TypeError("session_factory must return a SQLAlchemy Session")
    return session


def _read_stage_state(
    control_factory: sessionmaker[Session] | Callable[[], Session],
    job_id: str,
    stage_name: str,
) -> tuple[str | None, str | None]:
    session = _new_session(control_factory)
    try:
        job = session.get(JobRun, job_id)
        if job is None:
            raise ValueError(f"Unknown daily job: {job_id}")
        stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == job_id,
                JobStageRun.stage_name == stage_name,
            )
        )
        return (stage.status if stage is not None else None, job.current_stage)
    finally:
        session.close()


def _read_stage_status(
    control_factory: sessionmaker[Session] | Callable[[], Session],
    job_id: str,
    stage_name: str,
) -> str | None:
    return _read_stage_state(control_factory, job_id, stage_name)[0]


def _record_stage_failure(
    control_factory: sessionmaker[Session] | Callable[[], Session],
    *,
    job_id: str,
    stage_name: str,
    error: BaseException,
    lease_owner: str | None,
    lease_epoch: int | None,
    attempt_id: str | None,
    component_instance_id: str | None,
) -> None:
    control_session = _new_session(control_factory)
    try:
        control_session.begin()
        job_statement = (
            select(JobRun)
            .where(JobRun.job_id == job_id)
            .execution_options(populate_existing=True)
        )
        if control_session.get_bind().dialect.name == "postgresql":
            job_statement = job_statement.with_for_update()
        job = control_session.scalar(job_statement)
        if job is None:
            raise ValueError(f"Unknown daily job: {job_id}")
        if not _lease_matches(
            control_session,
            job,
            lease_owner=lease_owner,
            lease_epoch=lease_epoch,
            attempt_id=attempt_id,
            component_instance_id=component_instance_id,
        ):
            control_session.rollback()
            return
        now = datetime.now(UTC)
        stage = control_session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == job_id,
                JobStageRun.stage_name == stage_name,
            )
        )
        if stage is None:
            stage = JobStageRun(
                stage_run_id=_stage_run_id(job_id, stage_name),
                job_id=job_id,
                stage_name=stage_name,
                status="failed",
                checkpoint_json={},
                lease_epoch=int(job.lease_epoch or 0),
                started_at=now,
                finished_at=now,
                created_at=now,
                updated_at=now,
            )
            control_session.add(stage)
        else:
            if stage.status == "success":
                control_session.rollback()
                return
            stage.status = "failed"
            stage.lease_epoch = int(job.lease_epoch or 0)
            stage.finished_at = now
            stage.updated_at = now
            stage.checkpoint_json = {
                **(stage.checkpoint_json or {}),
                "status": "failed",
                "error": sanitize_error_message(str(error)),
            }
        summary = sanitize_error_message(str(error)) or error.__class__.__name__
        job.current_stage = stage_name
        if job.job_kind == "parent_sync" and job.parent_job_id:
            _record_range_parent_stage_failure(
                control_session,
                parent_job_id=job.parent_job_id,
                error_summary=summary,
                now=now,
            )
        # Failure is recorded on the stage checkpoint only.  The parent
        # supervisor classifies it and calls the fenced ``fail_job`` API so
        # JobRun, JobAttempt, ComponentHeartbeat, retry delay, and audit event
        # transition atomically.
        control_session.commit()
    except Exception:
        control_session.rollback()
        raise
    finally:
        control_session.close()


def _call_handler(handler: StageHandler, session: Session, job: JobRun) -> Any:
    """Support simple ``handler(session)`` and context-aware handlers."""

    try:
        parameters = inspect.signature(handler).parameters
    except (TypeError, ValueError):
        parameters = {}
    if len(parameters) >= 2:
        return handler(session, job)
    return handler(session)


def _handler_requires_independent_sessions(handler: StageHandler, job: JobRun) -> bool:
    marker = getattr(handler, "requires_independent_sessions", False)
    if callable(marker):
        return bool(marker(job))
    return bool(marker)


def _checkpoint_payload(output: Any) -> dict[str, Any]:
    if output is None:
        return {}
    if isinstance(output, StageHandlerOutput):
        return {str(key): value for key, value in output.checkpoint.items()}
    if isinstance(output, dict):
        return {str(key): value for key, value in output.items()}
    as_metadata = getattr(output, "as_metadata", None)
    if callable(as_metadata):
        metadata = as_metadata()
        if isinstance(metadata, dict):
            return metadata
    return {"result": str(output)[:512]}


def _stage_owned_snapshot(stage: JobStageRun) -> dict[str, Any]:
    return {
        attribute.key: deepcopy(getattr(stage, attribute.key))
        for attribute in stage.__mapper__.column_attrs
    }


def _apply_before_success_commit(
    session: Session,
    *,
    mutation: BeforeSuccessCommit,
    job: JobRun,
    stage: JobStageRun,
) -> None:
    before = _stage_owned_snapshot(stage)

    def reject_nested_commit(_session: Session) -> None:
        raise RuntimeError("before_success_commit cannot commit the runner transaction")

    event.listen(session, "before_commit", reject_nested_commit)
    try:
        mutation.apply(session, job=job, stage=stage)
    finally:
        event.remove(session, "before_commit", reject_nested_commit)
    if not session.in_transaction():
        raise RuntimeError("before_success_commit ended the runner transaction")
    if _stage_owned_snapshot(stage) != before:
        raise RuntimeError("before_success_commit modified stage-owned fields")


def _required_stage_names(job: JobRun) -> tuple[str, ...]:
    configured = (job.metadata_json or {}).get("required_stages")
    if isinstance(configured, list) and configured:
        return tuple(str(stage_name) for stage_name in configured)
    return ("collect", "materialize", "settle")


def _next_stage(stage_name: str) -> str | None:
    return _next_stage_in(stage_name, STAGE_ORDER)


def _next_stage_in(stage_name: str, stage_order: Sequence[str]) -> str | None:
    index = stage_order.index(stage_name)
    return stage_order[index + 1] if index + 1 < len(stage_order) else None


def _promote_range_parent_stage(
    session: Session,
    *,
    parent_job_id: str,
    parent_execution_job_id: str,
    required_stages: Sequence[str],
    checkpoint: Mapping[str, Any],
    now: datetime,
) -> None:
    parent_stage = session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    if parent_stage is None:
        parent_stage = JobStageRun(
            stage_run_id=_stage_run_id(parent_job_id, "collect_dimensions"),
            job_id=parent_job_id,
            stage_name="collect_dimensions",
            status="pending",
            checkpoint_json={},
            created_at=now,
            updated_at=now,
        )
        session.add(parent_stage)
    session.flush()
    statuses = dict(
        session.execute(
            select(JobStageRun.stage_name, JobStageRun.status).where(
                JobStageRun.job_id == parent_execution_job_id,
                JobStageRun.stage_name.in_(required_stages),
            )
        ).all()
    )
    all_success = all(statuses.get(stage_name) == "success" for stage_name in required_stages)
    any_failed = any(statuses.get(stage_name) == "failed" for stage_name in required_stages)
    parent_stage.status = "failed" if any_failed else ("success" if all_success else "pending")
    parent_stage.checkpoint_json = {
        **(parent_stage.checkpoint_json or {}),
        **dict(checkpoint),
        "stage": "collect_dimensions",
        "status": parent_stage.status,
        "required_stages": list(required_stages),
        "stage_statuses": statuses,
    }
    parent_stage.started_at = parent_stage.started_at or now
    parent_stage.finished_at = now if parent_stage.status in {"success", "failed"} else None
    parent_stage.committed_at = now if parent_stage.status == "success" else None
    parent_stage.updated_at = now


def _record_range_parent_stage_failure(
    session: Session,
    *,
    parent_job_id: str,
    error_summary: str,
    now: datetime,
) -> None:
    parent_stage = session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    if parent_stage is None:
        parent_stage = JobStageRun(
            stage_run_id=_stage_run_id(parent_job_id, "collect_dimensions"),
            job_id=parent_job_id,
            stage_name="collect_dimensions",
            checkpoint_json={},
            created_at=now,
            updated_at=now,
        )
        session.add(parent_stage)
    parent_stage.status = "failed"
    parent_stage.checkpoint_json = {
        **(parent_stage.checkpoint_json or {}),
        "stage": "collect_dimensions",
        "status": "failed",
        "error": error_summary,
    }
    parent_stage.started_at = parent_stage.started_at or now
    parent_stage.finished_at = now
    parent_stage.committed_at = None
    parent_stage.updated_at = now


def _stage_run_id(job_id: str, stage_name: str) -> str:
    return f"stage-{job_id}-{stage_name}"


def _assert_execution_lease(
    session: Session,
    job: JobRun,
    *,
    lease_owner: str | None,
    lease_epoch: int | None,
    attempt_id: str | None,
    component_instance_id: str | None,
) -> None:
    if lease_owner is None and lease_epoch is None and attempt_id is None:
        return
    if not _lease_matches(
        session,
        job,
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        attempt_id=attempt_id,
        component_instance_id=component_instance_id,
    ):
        raise RuntimeError("daily execution lease is no longer valid")


def _lease_matches(
    session: Session,
    job: JobRun,
    *,
    lease_owner: str | None,
    lease_epoch: int | None,
    attempt_id: str | None,
    component_instance_id: str | None,
) -> bool:
    if lease_owner is None and lease_epoch is None and attempt_id is None:
        return True
    if lease_owner is None or lease_epoch is None or attempt_id is None:
        return False
    if (
        job.status != "running"
        or job.lease_owner != lease_owner
        or int(job.lease_epoch or 0) != int(lease_epoch)
        or job.lease_expires_at is None
    ):
        return False
    if session.get_bind().dialect.name == "postgresql":
        database_now = session.scalar(select(func.clock_timestamp()))
    else:
        database_now = datetime.now(UTC)
    if database_now is None:
        return False
    lease_expires_at = job.lease_expires_at
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    if lease_expires_at <= database_now:
        return False
    attempt = session.scalar(
        select(JobAttempt).where(
            JobAttempt.job_id == job.job_id,
            JobAttempt.attempt_id == attempt_id,
            JobAttempt.lease_epoch == lease_epoch,
            JobAttempt.finished_at.is_(None),
            JobAttempt.component_instance_id == component_instance_id,
        )
    )
    return attempt is not None


def is_daily_execution_lease_live(
    session: Session,
    *,
    job_id: str,
    lease_owner: str | None,
    lease_epoch: int | None,
    attempt_id: str | None,
    component_instance_id: str | None,
    lock: bool = False,
) -> bool:
    """Read the current JobRun/Attempt fence for page-level child work."""

    job_statement = select(JobRun).where(JobRun.job_id == job_id)
    if lock and session.get_bind().dialect.name == "postgresql":
        job_statement = job_statement.with_for_update()
    job = session.scalar(job_statement)
    if job is None:
        return False
    return _lease_matches(
        session,
        job,
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        attempt_id=attempt_id,
        component_instance_id=component_instance_id,
    )
