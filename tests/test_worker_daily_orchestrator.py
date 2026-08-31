from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    ComponentHeartbeat,
    ComponentMetricSample,
    JobAttempt,
    JobEvent,
    JobRun,
    JobStageRun,
    OpsCommand,
)
from apps.worker import backfill, scheduler
from apps.worker.collectors.types import CollectionWindow
from apps.worker.daily_windows import (
    enqueue_finalize_if_ready,
    iter_shanghai_daily_windows,
    plan_daily_sync,
)
from apps.worker import daily_windows


CONTROL_TABLES = (
    JobRun.__table__,
    JobStageRun.__table__,
    ComponentHeartbeat.__table__,
    JobAttempt.__table__,
    JobEvent.__table__,
    ComponentMetricSample.__table__,
    OpsCommand.__table__,
)


def _complete_finalize_prerequisites(db_session: Session, plan) -> None:
    now = datetime(2026, 8, 4, tzinfo=UTC)
    for planned in plan.daily_jobs:
        child = db_session.get(JobRun, planned.job_id)
        assert child is not None
        child.status = "success"
        for stage_name in (child.metadata_json or {}).get("required_stages", []):
            checkpoint = {}
            if stage_name == "settle":
                checkpoint = {
                    "settlement_summary": {
                        "completed": True,
                        "impact_count": 0,
                        "coupon_count": 0,
                        "detail_count": 0,
                        "result_count": 0,
                        "adjustment_count": 0,
                        "last_impact_id": None,
                        "affected_months": [],
                        "affected_store_ids": [],
                    },
                    "store_score_snapshot": {
                        "deferred": True,
                        "consumer": "T3.4.finalize",
                        "affected_store_ids": [],
                        "rule_closure": "published-rules-and-eligible-stores",
                    },
                }
            db_session.add(
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
    required_stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == plan.parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    if required_stage is not None:
        required_stage.status = "success"
        required_stage.committed_at = now
        required_stage.finished_at = now
    db_session.flush()


def _control_plane_snapshot(
    factory: sessionmaker[Session],
) -> dict[str, tuple[str, ...]]:
    snapshot: dict[str, tuple[str, ...]] = {}
    with factory() as session:
        for table in CONTROL_TABLES:
            statement = table.select().order_by(*table.primary_key.columns)
            snapshot[table.name] = tuple(
                json.dumps(dict(row), default=str, sort_keys=True)
                for row in session.execute(statement).mappings()
            )
    return snapshot


def _assert_only_caller_event_changed(
    before: dict[str, tuple[str, ...]],
    after: dict[str, tuple[str, ...]],
    *,
    event_id: str,
) -> None:
    for table_name in before.keys() - {JobEvent.__tablename__}:
        assert after[table_name] == before[table_name]
    before_events = set(before[JobEvent.__tablename__])
    after_events = set(after[JobEvent.__tablename__])
    assert before_events <= after_events
    added_events = after_events - before_events
    assert len(added_events) == 1
    assert json.loads(added_events.pop())["event_id"] == event_id


def test_shanghai_half_open_range_is_exactly_three_natural_days() -> None:
    windows = list(
        iter_shanghai_daily_windows(date(2026, 8, 1), date(2026, 8, 4))
    )

    assert [window.business_date for window in windows] == [
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 8, 3),
    ]
    assert all(window.timezone_name == "Asia/Shanghai" for window in windows)
    assert all(window.start.hour == 0 and window.end.hour == 0 for window in windows)
    assert all(window.end - window.start == timedelta(days=1) for window in windows)
    assert all(window.start.utcoffset() == timedelta(hours=8) for window in windows)
    assert all(left.end == right.start for left, right in zip(windows, windows[1:]))
    assert windows[0].start.isoformat() == "2026-08-01T00:00:00+08:00"
    assert windows[-1].end.isoformat() == "2026-08-04T00:00:00+08:00"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 8, 1), date(2026, 8, 1)),
        (date(2026, 8, 2), date(2026, 8, 1)),
    ],
)
def test_shanghai_daily_window_rejects_empty_or_reversed_ranges(
    start: date,
    end: date,
) -> None:
    with pytest.raises(ValueError, match="end must be after start"):
        list(iter_shanghai_daily_windows(start, end))


def test_replayed_plan_returns_same_parent_children_and_preserves_state(
    db_session: Session,
) -> None:
    first = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    db_session.commit()

    first_child = db_session.get(JobRun, first.daily_jobs[0].job_id)
    assert first_child is not None
    first_child.status = "success"
    first_child.attempt_count = 2
    first_child.lease_epoch = 2
    db_session.add(
        JobEvent(
            event_id="event-preserved",
            job_id=first_child.job_id,
            event_type="job_succeeded",
            from_status="running",
            to_status="success",
            actor_type="worker",
            actor_id="worker-1",
            payload_json={},
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )
    db_session.commit()

    replay = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="scheduler",
    )
    db_session.commit()

    assert replay.parent_job_id == first.parent_job_id
    assert [job.job_id for job in replay.daily_jobs] == [
        job.job_id for job in first.daily_jobs
    ]
    assert [job.disposition for job in replay.daily_jobs] == [
        "skipped",
        "ready",
        "ready",
    ]
    assert db_session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.job_kind == "range_sync")
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.job_kind == "date_sync")
    ) == 3
    assert db_session.scalar(
        select(func.count()).select_from(JobStageRun).where(
            JobStageRun.job_id == first.parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    ) == 1
    preserved = db_session.get(JobRun, first_child.job_id)
    assert preserved is not None
    assert (preserved.status, preserved.attempt_count, preserved.lease_epoch) == (
        "success",
        2,
        2,
    )
    assert db_session.get(JobEvent, "event-preserved") is not None


@pytest.mark.parametrize(
    (
        "target",
        "expected_parent_targets",
        "expected_daily_targets",
        "expected_daily_job_count",
    ),
    [
        (
            "all",
            ["shop_pois", "aweme_bindings"],
            ["orders", "refunds", "clues", "verify_records", "clue_center", "settlement"],
            3,
        ),
        ("refunds", [], ["refunds"], 3),
        ("shop_pois", ["shop_pois"], [], 0),
        ("aweme_bindings", ["aweme_bindings"], [], 0),
        ("backend_aweme_export", ["backend_aweme_export"], [], 0),
    ],
)
def test_global_dimension_targets_are_partitioned_from_daily_execution(
    db_session: Session,
    target: str,
    expected_parent_targets: list[str],
    expected_daily_targets: list[str],
    expected_daily_job_count: int,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target=target,
        requested_by="highest-admin",
        trigger_source="manual",
    )
    db_session.flush()

    parent = db_session.get(JobRun, plan.parent_job_id)
    assert parent is not None
    assert parent.metadata_json["parent_targets"] == expected_parent_targets
    assert parent.metadata_json["daily_targets"] == expected_daily_targets
    assert len(plan.daily_jobs) == expected_daily_job_count

    dimension_stages = list(
        db_session.scalars(
            select(JobStageRun).where(
                JobStageRun.job_id == plan.parent_job_id,
                JobStageRun.stage_name == "collect_dimensions",
            )
        )
    )
    assert len(dimension_stages) == (1 if expected_parent_targets else 0)
    if dimension_stages:
        assert dimension_stages[0].checkpoint_json["parent_targets"] == expected_parent_targets
        assert dimension_stages[0].checkpoint_json["daily_targets"] == expected_daily_targets

    for planned in plan.daily_jobs:
        child = db_session.get(JobRun, planned.job_id)
        assert child is not None
        assert child.metadata_json["parent_targets"] == expected_parent_targets
        assert child.metadata_json["daily_targets"] == expected_daily_targets
        assert not set(child.metadata_json["parent_targets"]).intersection(
            child.metadata_json["daily_targets"]
        )
        assert "shop_pois" not in child.metadata_json["daily_targets"]
        assert "aweme_bindings" not in child.metadata_json["daily_targets"]


@pytest.mark.parametrize(
    "target",
    [
        "all",
        "orders",
        "refunds",
        "clues",
        "verify_records",
        "clue_center",
        "settlement",
        "shop_pois",
        "aweme_bindings",
        "backend_aweme_export",
    ],
)
def test_planner_stamps_incremental_modes_on_every_heavy_execution(
    db_session: Session,
    target: str,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        target=target,
        requested_by="highest-admin",
        trigger_source="candidate-acceptance",
        config_version=f"incremental-mode-{target}",
    )
    db_session.flush()

    executions = tuple(
        db_session.scalars(
            select(JobRun)
            .where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind.in_(("parent_sync", "date_sync")),
            )
            .order_by(JobRun.job_kind, JobRun.job_id)
        )
    )
    assert executions
    for execution in executions:
        metadata = execution.metadata_json or {}
        required_stages = set(metadata["required_stages"])
        if "materialize" in required_stages:
            assert metadata["clue_materialization_mode"] == "incremental"
        else:
            assert "clue_materialization_mode" not in metadata
        if "settle" in required_stages:
            assert metadata["settlement_mode"] == "incremental"
        else:
            assert "settlement_mode" not in metadata


def test_replay_rejects_daily_child_missing_incremental_mode(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        target="clue_center",
        requested_by="highest-admin",
        trigger_source="candidate-acceptance",
        config_version="incremental-mode-replay",
    )
    child = db_session.get(JobRun, plan.daily_jobs[0].job_id)
    assert child is not None
    assert child.metadata_json["clue_materialization_mode"] == "incremental"
    child.metadata_json = {
        key: value
        for key, value in child.metadata_json.items()
        if key != "clue_materialization_mode"
    }
    db_session.commit()

    with pytest.raises(RuntimeError, match="daily child identity"):
        plan_daily_sync(
            db_session,
            start=date(2026, 8, 1),
            end=date(2026, 8, 2),
            target="clue_center",
            requested_by="highest-admin",
            trigger_source="candidate-acceptance",
            config_version="incremental-mode-replay",
        )


def test_incremental_window_rejects_non_shanghai_timezone_configuration() -> None:
    with pytest.raises(ValueError, match="must be Asia/Shanghai"):
        scheduler.resolve_incremental_collection_window(
            now=datetime.fromisoformat("2026-06-15T17:00:00+00:00"),
            env={
                "WORKER_ROLLING_DAYS": "1",
                "DOUYIN_COLLECT_TIMEZONE": "UTC",
            },
        )


def test_scheduler_production_entrypoint_honors_configured_timezone(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    monkeypatch.setenv("DOUYIN_COLLECT_TIMEZONE", "UTC")

    with pytest.raises(ValueError, match="must be Asia/Shanghai"):
        scheduler.run_incremental_collection_chunks(
            factory,
            SimpleNamespace(rolling_days=3, history_chunk_days=1),
        )

    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_backfill_rejects_non_shanghai_timezone_configuration(
    db_session: Session,
) -> None:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    with pytest.raises(ValueError, match="must be Asia/Shanghai"):
        backfill.run_backfill(
            factory=factory,
            start="2026-08-01",
            end="2026-08-04",
            timezone_name="UTC",
        )


def test_backfill_clamps_explicit_end_to_latest_closed_shanghai_day(
    db_session: Session,
) -> None:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    plan = backfill.run_backfill(
        factory=factory,
        start="2026-08-05",
        end="2026-08-08",
        now=datetime.fromisoformat("2026-08-06T12:00:00+08:00"),
    )

    assert [job.business_date for job in plan.daily_jobs] == [date(2026, 8, 5)]
    assert plan.window_end.isoformat() == "2026-08-06T00:00:00+08:00"


def test_backfill_rejects_range_without_a_closed_shanghai_day(
    db_session: Session,
) -> None:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    with pytest.raises(ValueError, match="closed Shanghai business day"):
        backfill.run_backfill(
            factory=factory,
            start="2026-08-06",
            end="2026-08-08",
            now=datetime.fromisoformat("2026-08-06T12:00:00+08:00"),
        )

    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


@pytest.mark.parametrize(
    "blocking_status",
    ["pending", "retry_wait", "running", "failed", "cancelled", "partial"],
)
def test_finalize_is_blocked_until_every_date_and_required_parent_stage_succeeds(
    db_session: Session,
    blocking_status: str,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    for planned in plan.daily_jobs:
        child = db_session.get(JobRun, planned.job_id)
        assert child is not None
        child.status = "success"
    blocked_child = db_session.get(JobRun, plan.daily_jobs[-1].job_id)
    assert blocked_child is not None
    blocked_child.status = blocking_status
    required_stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == plan.parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    assert required_stage is not None
    required_stage.status = "success"
    required_stage.committed_at = required_stage.created_at
    db_session.flush()

    assert enqueue_finalize_if_ready(db_session, plan.parent_job_id) is None
    assert db_session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.job_kind == "finalize")
    ) == 0


def test_terminal_child_failures_mark_finished_range_parent_failed(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 3),
        target="orders",
        requested_by="highest-admin",
        trigger_source="manual",
        config_version="terminal-parent-failure-v1",
    )
    first = db_session.get(JobRun, plan.daily_jobs[0].job_id)
    second = db_session.get(JobRun, plan.daily_jobs[1].job_id)
    assert first is not None and second is not None
    first.status = "failed"
    first.finished_at = datetime(2026, 8, 3, tzinfo=UTC)
    first.error_code = "douyin_rate_limited"
    second.status = "pending"
    db_session.flush()

    reconcile = getattr(daily_windows, "reconcile_terminal_range_parents", None)
    assert callable(reconcile), "terminal range parent reconciler is missing"
    assert reconcile(db_session) == 0
    parent = db_session.get(JobRun, plan.parent_job_id)
    assert parent is not None and parent.status == "pending"

    second.status = "success"
    second.finished_at = datetime(2026, 8, 3, 0, 1, tzinfo=UTC)
    db_session.flush()

    assert reconcile(db_session) == 1
    db_session.refresh(parent)
    assert parent.status == "failed"
    assert parent.success_count == 1
    assert parent.failed_count == 1
    assert parent.error_code == "child_jobs_failed"
    assert parent.finished_at is not None


def test_finalize_is_enqueued_once_after_all_prerequisites_succeed(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    _complete_finalize_prerequisites(db_session, plan)

    first = enqueue_finalize_if_ready(db_session, plan.parent_job_id)
    second = enqueue_finalize_if_ready(db_session, plan.parent_job_id)
    db_session.commit()

    assert first is not None
    assert second is not None
    assert second.job_id == first.job_id
    assert first.parent_job_id == plan.parent_job_id
    assert first.job_kind == "finalize"
    assert first.current_stage == "finalize"
    assert first.status == "pending"
    assert db_session.scalar(
        select(func.count()).select_from(JobRun).where(JobRun.job_kind == "finalize")
    ) == 1


def test_optional_parent_stage_does_not_block_finalize(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 3),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    _complete_finalize_prerequisites(db_session, plan)
    db_session.add(
        JobStageRun(
            stage_run_id="stage-optional-observation",
            job_id=plan.parent_job_id,
            stage_name="optional_observation",
            status="pending",
            checkpoint_json={"required_for_finalize": False},
            lease_epoch=0,
            created_at=datetime(2026, 8, 3, tzinfo=UTC),
            updated_at=datetime(2026, 8, 3, tzinfo=UTC),
        )
    )
    db_session.flush()

    assert enqueue_finalize_if_ready(db_session, plan.parent_job_id) is not None
    assert db_session.scalar(
        select(func.count()).select_from(JobStageRun).where(
            JobStageRun.job_id == plan.parent_job_id,
            JobStageRun.stage_name == "finalize",
        )
    ) == 1


def test_scheduler_and_backfill_replay_the_same_plan_without_running_pipeline(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    source_window = CollectionWindow(
        start=datetime.fromisoformat("2026-08-01T00:00:00+08:00"),
        end=datetime.fromisoformat("2026-08-04T00:00:00+08:00"),
        timezone_name="Asia/Shanghai",
    )

    def forbidden_pipeline(*_args, **_kwargs):
        raise AssertionError("scheduler/backfill must only plan and enqueue")

    monkeypatch.setattr(
        scheduler,
        "run_collect_and_settle",
        forbidden_pipeline,
        raising=False,
    )
    monkeypatch.setattr(
        backfill,
        "run_collect_and_settle",
        forbidden_pipeline,
        raising=False,
    )
    monkeypatch.setattr(
        scheduler,
        "resolve_incremental_collection_window",
        lambda env=None: source_window,
    )

    scheduled = scheduler.run_incremental_collection_chunks(
        factory,
        SimpleNamespace(rolling_days=3, history_chunk_days=1),
    )
    replayed = backfill.run_backfill(
        factory=factory,
        start=source_window.start,
        end=source_window.end,
    )

    assert replayed.parent_job_id == scheduled.parent_job_id
    assert [job.job_id for job in replayed.daily_jobs] == [
        job.job_id for job in scheduled.daily_jobs
    ]
    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(JobRun).where(
                JobRun.job_kind == "range_sync"
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(JobRun).where(
                JobRun.job_kind == "date_sync"
            )
        ) == 3


def test_replay_preserves_retry_wait_and_running_lease_fields(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="orders",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    retrying = db_session.get(JobRun, plan.daily_jobs[0].job_id)
    running = db_session.get(JobRun, plan.daily_jobs[1].job_id)
    assert retrying is not None and running is not None
    retrying.status = "retry_wait"
    retrying.current_stage = "materialize"
    retrying.attempt_count = 1
    retrying.lease_epoch = 1
    retrying.next_retry_at = datetime(2026, 8, 5, tzinfo=UTC)
    running.status = "running"
    running.current_stage = "settle"
    running.attempt_count = 2
    running.lease_owner = "worker-preserved"
    running.lease_epoch = 2
    running.lease_expires_at = datetime(2026, 8, 6, tzinfo=UTC)
    running.heartbeat_at = datetime(2026, 8, 5, tzinfo=UTC)
    db_session.commit()
    retry_timestamp = retrying.next_retry_at
    running_lease_expires_at = running.lease_expires_at
    running_heartbeat_at = running.heartbeat_at

    replay = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="orders",
        requested_by="highest-admin",
        trigger_source="backfill",
    )
    db_session.commit()

    assert [job.disposition for job in replay.daily_jobs[:2]] == ["ready", "blocked"]
    preserved_retry = db_session.get(JobRun, retrying.job_id)
    preserved_running = db_session.get(JobRun, running.job_id)
    assert preserved_retry is not None and preserved_running is not None
    assert (
        preserved_retry.status,
        preserved_retry.current_stage,
        preserved_retry.attempt_count,
        preserved_retry.lease_epoch,
        preserved_retry.next_retry_at,
    ) == (
        "retry_wait",
        "materialize",
        1,
        1,
        retry_timestamp,
    )
    assert (
        preserved_running.status,
        preserved_running.current_stage,
        preserved_running.attempt_count,
        preserved_running.lease_owner,
        preserved_running.lease_epoch,
        preserved_running.lease_expires_at,
        preserved_running.heartbeat_at,
    ) == (
        "running",
        "settle",
        2,
        "worker-preserved",
        2,
        running_lease_expires_at,
        running_heartbeat_at,
    )


def test_target_source_and_config_version_are_part_of_parent_identity(
    db_session: Session,
) -> None:
    common = {
        "session": db_session,
        "start": date(2026, 8, 1),
        "end": date(2026, 8, 2),
        "requested_by": "highest-admin",
        "trigger_source": "manual",
    }
    baseline = plan_daily_sync(target="orders", **common)
    other_target = plan_daily_sync(target="settlement", **common)
    other_source = plan_daily_sync(
        target="orders",
        data_source="douyin-secondary",
        **common,
    )
    other_version = plan_daily_sync(
        target="orders",
        config_version="daily-sync-v1",
        **common,
    )

    assert len(
        {
            baseline.parent_job_id,
            other_target.parent_job_id,
            other_source.parent_job_id,
            other_version.parent_job_id,
        }
    ) == 4


def test_incremental_mode_contract_bumps_default_config_version_without_replaying_v2(
    db_session: Session,
) -> None:
    legacy = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        target="all",
        requested_by="highest-admin",
        trigger_source="migration-test",
        config_version="daily-sync-v2",
    )
    for child in legacy.daily_jobs:
        row = db_session.get(JobRun, child.job_id)
        assert row is not None
        row.status = "success"
    db_session.flush()

    upgraded = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        target="all",
        requested_by="highest-admin",
        trigger_source="migration-test",
    )
    assert upgraded.parent_job_id != legacy.parent_job_id
    assert all(
        db_session.get(JobRun, child.job_id).config_version == "daily-sync-v3"
        and db_session.get(JobRun, child.job_id).status == "pending"
        for child in upgraded.daily_jobs
    )
    assert all(
        db_session.get(JobRun, child.job_id).config_version == "daily-sync-v2"
        and db_session.get(JobRun, child.job_id).status == "success"
        for child in legacy.daily_jobs
    )


def test_planner_rejects_unknown_target_before_creating_control_records(
    db_session: Session,
) -> None:
    with pytest.raises(ValueError, match="Unsupported daily sync target"):
        plan_daily_sync(
            db_session,
            start=date(2026, 8, 1),
            end=date(2026, 8, 2),
            target="ordres",
            requested_by="highest-admin",
            trigger_source="manual",
        )

    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_replay_rejects_tampered_parent_target_partition_without_resetting_state(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    parent = db_session.get(JobRun, plan.parent_job_id)
    assert parent is not None
    parent.status = "running"
    parent.attempt_count = 2
    parent.metadata_json = {
        **parent.metadata_json,
        "daily_targets": ["orders", "shop_pois"],
    }
    db_session.commit()

    with pytest.raises(RuntimeError, match="parent identity"):
        plan_daily_sync(
            db_session,
            start=date(2026, 8, 1),
            end=date(2026, 8, 4),
            target="all",
            requested_by="highest-admin",
            trigger_source="scheduler",
        )

    preserved = db_session.get(JobRun, plan.parent_job_id)
    assert preserved is not None
    assert (preserved.status, preserved.attempt_count) == ("running", 2)
    assert preserved.metadata_json["daily_targets"] == ["orders", "shop_pois"]


@pytest.mark.parametrize(
    "tampered_field",
    [
        "parent_job_id",
        "business_date",
        "data_source",
        "config_version",
        "window_start",
        "window_end",
        "idempotency_key_hash",
        "execution_slot",
        "metadata_target",
        "metadata_parent_targets",
        "metadata_daily_targets",
        "metadata_source_window",
    ],
)
def test_replay_rejects_tampered_daily_child_identity_without_resetting_state(
    db_session: Session,
    tampered_field: str,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    child = db_session.get(JobRun, plan.daily_jobs[0].job_id)
    assert child is not None
    child.status = "running"
    child.attempt_count = 2
    child.lease_epoch = 2
    child.lease_owner = "worker-preserved"
    if tampered_field == "parent_job_id":
        other = plan_daily_sync(
            db_session,
            start=date(2026, 8, 10),
            end=date(2026, 8, 13),
            target="settlement",
            requested_by="highest-admin",
            trigger_source="manual",
        )
        child.parent_job_id = other.parent_job_id
    elif tampered_field == "business_date":
        child.business_date = date(2026, 8, 9)
    elif tampered_field == "data_source":
        child.data_source = "tampered-source"
    elif tampered_field == "config_version":
        child.config_version = "tampered-version"
    elif tampered_field == "window_start":
        child.window_start = datetime.fromisoformat("2026-07-31T00:00:00+08:00")
    elif tampered_field == "window_end":
        child.window_end = datetime.fromisoformat("2026-08-03T00:00:00+08:00")
    elif tampered_field == "idempotency_key_hash":
        child.idempotency_key_hash = "0" * 64
    elif tampered_field == "execution_slot":
        child.execution_slot = None
    else:
        metadata = dict(child.metadata_json)
        if tampered_field == "metadata_target":
            metadata["target"] = "settlement"
        elif tampered_field == "metadata_parent_targets":
            metadata["parent_targets"] = []
        elif tampered_field == "metadata_daily_targets":
            metadata["daily_targets"] = ["orders", "shop_pois"]
        elif tampered_field == "metadata_source_window":
            metadata["source_window"] = {
                **metadata["source_window"],
                "end": "2026-08-09T00:00:00+08:00",
            }
        child.metadata_json = metadata
    db_session.commit()

    with pytest.raises(RuntimeError):
        plan_daily_sync(
            db_session,
            start=date(2026, 8, 1),
            end=date(2026, 8, 4),
            target="all",
            requested_by="highest-admin",
            trigger_source="backfill",
        )

    preserved = db_session.get(JobRun, child.job_id)
    assert preserved is not None
    assert (
        preserved.status,
        preserved.attempt_count,
        preserved.lease_epoch,
        preserved.lease_owner,
    ) == ("running", 2, 2, "worker-preserved")


def test_plan_validation_failure_rolls_back_only_planner_writes(
    db_session: Session,
) -> None:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    with factory.begin() as session:
        plan = plan_daily_sync(
            session,
            start=date(2026, 8, 1),
            end=date(2026, 8, 4),
            target="all",
            requested_by="highest-admin",
            trigger_source="manual",
        )
    with factory.begin() as session:
        first_child = session.get(JobRun, plan.daily_jobs[0].job_id)
        missing_child = session.get(JobRun, plan.daily_jobs[-1].job_id)
        assert first_child is not None and missing_child is not None
        first_child.execution_slot = None
        session.delete(missing_child)

    before = _control_plane_snapshot(factory)
    caller_event_id = "caller-event-after-plan-failure"
    with factory.begin() as session:
        session.add(
            JobEvent(
                event_id=caller_event_id,
                job_id=plan.parent_job_id,
                event_type="caller_state",
                actor_type="system",
                payload_json={"owned_by": "caller"},
                occurred_at=datetime(2026, 8, 5, tzinfo=UTC),
            )
        )
        with pytest.raises(RuntimeError, match="daily child identity"):
            plan_daily_sync(
                session,
                start=date(2026, 8, 1),
                end=date(2026, 8, 4),
                target="all",
                requested_by="highest-admin",
                trigger_source="replay",
            )
        session.flush()

    after = _control_plane_snapshot(factory)
    _assert_only_caller_event_changed(before, after, event_id=caller_event_id)
    with factory() as session:
        assert session.get(JobRun, plan.daily_jobs[-1].job_id) is None
        assert session.get(JobEvent, caller_event_id) is not None


def test_finalize_conflict_rolls_back_only_finalizer_writes(
    db_session: Session,
) -> None:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    conflicting_stage_id = "stage-conflicting-finalize"
    with factory.begin() as session:
        plan = plan_daily_sync(
            session,
            start=date(2026, 8, 1),
            end=date(2026, 8, 3),
            target="settlement",
            requested_by="highest-admin",
            trigger_source="manual",
        )
        _complete_finalize_prerequisites(session, plan)
        session.add(
            JobStageRun(
                stage_run_id=conflicting_stage_id,
                job_id=plan.parent_job_id,
                stage_name="finalize",
                status="pending",
                checkpoint_json={"required_for_finalize": False},
                lease_epoch=0,
                created_at=datetime(2026, 8, 3, tzinfo=UTC),
                updated_at=datetime(2026, 8, 3, tzinfo=UTC),
            )
        )

    before = _control_plane_snapshot(factory)
    caller_event_id = "caller-event-after-finalize-failure"
    with factory.begin() as session:
        session.add(
            JobEvent(
                event_id=caller_event_id,
                job_id=plan.parent_job_id,
                event_type="caller_state",
                actor_type="system",
                payload_json={"owned_by": "caller"},
                occurred_at=datetime(2026, 8, 5, tzinfo=UTC),
            )
        )
        with pytest.raises(RuntimeError, match="parent stage insert"):
            enqueue_finalize_if_ready(session, plan.parent_job_id)
        session.flush()

    after = _control_plane_snapshot(factory)
    _assert_only_caller_event_changed(before, after, event_id=caller_event_id)
    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(JobRun).where(
                JobRun.parent_job_id == plan.parent_job_id,
                JobRun.job_kind == "finalize",
            )
        ) == 0
        conflicting_stage = session.get(JobStageRun, conflicting_stage_id)
        assert conflicting_stage is not None
        assert conflicting_stage.stage_name == "finalize"
        assert conflicting_stage.status == "pending"
        assert conflicting_stage.checkpoint_json == {"required_for_finalize": False}


def test_finalize_rejects_incomplete_daily_child_set(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    for planned in plan.daily_jobs[:-1]:
        child = db_session.get(JobRun, planned.job_id)
        assert child is not None
        child.status = "success"
    missing_child = db_session.get(JobRun, plan.daily_jobs[-1].job_id)
    assert missing_child is not None
    db_session.delete(missing_child)
    required_stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == plan.parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    assert required_stage is not None
    required_stage.status = "success"
    required_stage.committed_at = datetime(2026, 8, 4, tzinfo=UTC)
    db_session.commit()

    with pytest.raises(RuntimeError, match="daily plan is incomplete"):
        enqueue_finalize_if_ready(db_session, plan.parent_job_id)

    assert db_session.scalar(
        select(func.count()).select_from(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id,
            JobRun.job_kind == "finalize",
        )
    ) == 0

def test_finalize_rejects_tampered_daily_child_identity(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    for planned in plan.daily_jobs:
        child = db_session.get(JobRun, planned.job_id)
        assert child is not None
        child.status = "success"
    tampered_child = db_session.get(JobRun, plan.daily_jobs[0].job_id)
    assert tampered_child is not None
    tampered_child.window_end = datetime.fromisoformat("2026-08-03T00:00:00+08:00")
    required_stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == plan.parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    assert required_stage is not None
    required_stage.status = "success"
    required_stage.committed_at = datetime(2026, 8, 4, tzinfo=UTC)
    db_session.commit()

    with pytest.raises(RuntimeError, match="daily child identity"):
        enqueue_finalize_if_ready(db_session, plan.parent_job_id)

    assert db_session.scalar(
        select(func.count()).select_from(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id,
            JobRun.job_kind == "finalize",
        )
    ) == 0


def test_replay_rejects_tampered_global_stage_checkpoint_without_resetting_state(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == plan.parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    assert stage is not None
    stage.status = "running"
    stage.lease_epoch = 2
    stage.checkpoint_json = {
        "required_for_finalize": True,
        "parent_targets": [],
        "daily_targets": ["orders"],
        "runtime_progress": 19,
    }
    db_session.commit()

    with pytest.raises(RuntimeError, match="parent stage identity"):
        plan_daily_sync(
            db_session,
            start=date(2026, 8, 1),
            end=date(2026, 8, 4),
            target="all",
            requested_by="highest-admin",
            trigger_source="replay",
        )

    preserved = db_session.get(JobStageRun, stage.stage_run_id)
    assert preserved is not None
    assert (preserved.status, preserved.lease_epoch) == ("running", 2)
    assert preserved.checkpoint_json["parent_targets"] == []
    assert preserved.checkpoint_json["runtime_progress"] == 19


def test_finalize_replay_rejects_tampered_stage_checkpoint_without_resetting_state(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 3),
        target="settlement",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    _complete_finalize_prerequisites(db_session, plan)
    finalize = enqueue_finalize_if_ready(db_session, plan.parent_job_id)
    assert finalize is not None
    db_session.commit()
    stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == plan.parent_job_id,
            JobStageRun.stage_name == "finalize",
        )
    )
    assert stage is not None
    stage.status = "running"
    stage.lease_epoch = 2
    stage.checkpoint_json = {
        "required_for_finalize": True,
        "runtime_progress": 7,
    }
    db_session.commit()

    with pytest.raises(RuntimeError, match="parent stage identity"):
        enqueue_finalize_if_ready(db_session, plan.parent_job_id)

    preserved = db_session.get(JobStageRun, stage.stage_run_id)
    assert preserved is not None
    assert (preserved.status, preserved.lease_epoch) == ("running", 2)
    assert preserved.checkpoint_json == {
        "required_for_finalize": True,
        "runtime_progress": 7,
    }


def test_finalize_rejects_missing_required_parent_stage(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    for planned in plan.daily_jobs:
        child = db_session.get(JobRun, planned.job_id)
        assert child is not None
        child.status = "success"
    required_stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == plan.parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    assert required_stage is not None
    db_session.delete(required_stage)
    db_session.commit()

    with pytest.raises(RuntimeError, match="required parent stage is missing"):
        enqueue_finalize_if_ready(db_session, plan.parent_job_id)

    assert db_session.scalar(
        select(func.count()).select_from(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id,
            JobRun.job_kind == "finalize",
        )
    ) == 0


def test_finalize_rejects_tampered_required_parent_stage_flag(
    db_session: Session,
) -> None:
    plan = plan_daily_sync(
        db_session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 4),
        target="all",
        requested_by="highest-admin",
        trigger_source="manual",
    )
    for planned in plan.daily_jobs:
        child = db_session.get(JobRun, planned.job_id)
        assert child is not None
        child.status = "success"
    required_stage = db_session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == plan.parent_job_id,
            JobStageRun.stage_name == "collect_dimensions",
        )
    )
    assert required_stage is not None
    required_stage.status = "success"
    required_stage.committed_at = datetime(2026, 8, 4, tzinfo=UTC)
    required_stage.checkpoint_json = {
        **required_stage.checkpoint_json,
        "required_for_finalize": False,
    }
    db_session.commit()

    with pytest.raises(RuntimeError, match="parent stage identity"):
        enqueue_finalize_if_ready(db_session, plan.parent_job_id)

    assert db_session.scalar(
        select(func.count()).select_from(JobRun).where(
            JobRun.parent_job_id == plan.parent_job_id,
            JobRun.job_kind == "finalize",
        )
    ) == 0
