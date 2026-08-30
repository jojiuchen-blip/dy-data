from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import JobEvent, JobRun, JobStageRun
from apps.worker.collectors.refunds import RefundCollectionError, collect_refunds
from apps.worker.collectors.types import CollectionWindow
from apps.worker.stage_runner import STAGE_ORDER, run_daily_stages


def _seed_job(
    session: Session,
    job_id: str = "date-stage-1",
    *,
    business_date: date = date(2026, 8, 5),
) -> None:
    now = datetime.now(UTC)
    window_end_date = business_date.fromordinal(business_date.toordinal() + 1)
    session.add(
        JobRun(
            job_id=job_id,
            job_name="date_sync",
            status="pending",
            started_at=now,
            success_count=0,
            failed_count=0,
            metadata_json={},
            parent_job_id="range-parent",
            job_kind="date_sync",
            execution_slot="heavy_sync",
            business_date=business_date,
            data_source="douyin",
            config_version="v1",
            window_start=datetime.combine(business_date, datetime.min.time(), tzinfo=UTC),
            window_end=datetime.combine(window_end_date, datetime.min.time(), tzinfo=UTC),
            current_stage="collect",
            attempt_count=0,
            max_attempts=3,
            lease_epoch=0,
        )
    )
    session.commit()


def test_collect_checkpoint_survives_materialize_failure_and_resume_skips_collect(
    db_session: Session,
) -> None:
    _seed_job(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    calls: list[str] = []

    def collect(session: Session) -> None:
        calls.append("collect")
        session.add(
            JobEvent(
                event_id="business-collect",
                job_id="date-stage-1",
                event_type="business_collect",
                actor_type="worker",
                payload_json={"rows": 1},
                occurred_at=datetime.now(UTC),
            )
        )

    def fail_materialize(session: Session) -> None:
        calls.append("materialize")
        session.add(
            JobEvent(
                event_id="business-materialize-rolled-back",
                job_id="date-stage-1",
                event_type="business_materialize",
                actor_type="worker",
                payload_json={},
                occurred_at=datetime.now(UTC),
            )
        )
        raise RuntimeError("materialize failed")

    with pytest.raises(RuntimeError, match="materialize failed"):
        run_daily_stages(
            factory,
            job_id="date-stage-1",
            handlers={"collect": collect, "materialize": fail_materialize},
        )

    with factory() as verify:
        collect_stage = verify.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == "date-stage-1",
                JobStageRun.stage_name == "collect",
            )
        )
        materialize_stage = verify.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == "date-stage-1",
                JobStageRun.stage_name == "materialize",
            )
        )
        assert collect_stage is not None and collect_stage.status == "success"
        assert materialize_stage is not None and materialize_stage.status == "failed"
        assert verify.get(JobEvent, "business-collect") is not None
        assert verify.get(JobEvent, "business-materialize-rolled-back") is None

    def materialize(session: Session) -> None:
        calls.append("materialize")
        session.add(
            JobEvent(
                event_id="business-materialize",
                job_id="date-stage-1",
                event_type="business_materialize",
                actor_type="worker",
                payload_json={"rows": 1},
                occurred_at=datetime.now(UTC),
            )
        )

    def settle(session: Session) -> None:
        calls.append("settle")
        session.add(
            JobEvent(
                event_id="business-settle",
                job_id="date-stage-1",
                event_type="business_settle",
                actor_type="worker",
                payload_json={"rows": 1},
                occurred_at=datetime.now(UTC),
            )
        )

    result = run_daily_stages(
        factory,
        job_id="date-stage-1",
        handlers={"collect": collect, "materialize": materialize, "settle": settle},
    )

    assert result.status == "success"
    assert calls == ["collect", "materialize", "materialize", "settle"]
    with factory() as verify:
        stages = list(
            verify.scalars(
                select(JobStageRun)
                .where(JobStageRun.job_id == "date-stage-1")
                .order_by(JobStageRun.stage_name)
            )
        )
        assert {stage.stage_name: stage.status for stage in stages} == {
            "collect": "success",
            "materialize": "success",
            "settle": "success",
        }


def test_stage_transaction_rolls_back_business_write_and_checkpoint_together(
    db_session: Session,
) -> None:
    _seed_job(db_session, "date-stage-crash")
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)

    def crash(session: Session) -> None:
        session.add(
            JobEvent(
                event_id="business-crash",
                job_id="date-stage-crash",
                event_type="business_collect",
                actor_type="worker",
                payload_json={},
                occurred_at=datetime.now(UTC),
            )
        )
        raise RuntimeError("crash in transaction")

    with pytest.raises(RuntimeError, match="crash in transaction"):
        run_daily_stages(factory, job_id="date-stage-crash", handlers={"collect": crash})

    with factory() as verify:
        assert verify.get(JobEvent, "business-crash") is None
        stage = verify.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == "date-stage-crash",
                JobStageRun.stage_name == "collect",
            )
        )
        assert stage is not None and stage.status == "failed"


def test_commit_then_crash_does_not_repeat_successful_stage(db_session: Session) -> None:
    _seed_job(db_session, "date-stage-after-commit")
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    calls: list[str] = []

    def collect(session: Session) -> None:
        calls.append("collect")
        session.add(
            JobEvent(
                event_id="business-after-commit",
                job_id="date-stage-after-commit",
                event_type="business_collect",
                actor_type="worker",
                payload_json={},
                occurred_at=datetime.now(UTC),
            )
        )

    with pytest.raises(RuntimeError, match="after commit"):
        run_daily_stages(
            factory,
            job_id="date-stage-after-commit",
            handlers={"collect": collect},
            after_stage_commit=lambda _stage: (_ for _ in ()).throw(
                RuntimeError("after commit")
            ),
        )

    result = run_daily_stages(
        factory,
        job_id="date-stage-after-commit",
        handlers={"collect": collect, "materialize": lambda _session: None, "settle": lambda _session: None},
    )
    assert result.status == "success"
    assert calls == ["collect"]
    with factory() as verify:
        assert verify.scalar(
            select(JobStageRun.status).where(
                JobStageRun.job_id == "date-stage-after-commit",
                JobStageRun.stage_name == "collect",
            )
        ) == "success"


def test_each_stage_gets_a_fresh_closed_session(db_session: Session) -> None:
    _seed_job(db_session, "date-stage-sessions")
    base_factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    sessions: list[Session] = []

    class TrackingSession(Session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.closed_for_test = False

        def close(self) -> None:
            self.closed_for_test = True
            super().close()

    def factory() -> TrackingSession:
        session = TrackingSession(bind=db_session.get_bind(), autoflush=False)
        sessions.append(session)
        return session

    run_daily_stages(
        factory,
        job_id="date-stage-sessions",
        handlers={stage: (lambda _session: None) for stage in STAGE_ORDER},
    )

    assert len(sessions) == 6  # one control read + one write session per stage
    assert all(session.closed_for_test for session in sessions)
    assert len({id(session) for session in sessions}) == len(sessions)


def test_independent_handler_enters_after_stage_transaction_is_released(
    db_session: Session,
) -> None:
    _seed_job(db_session, "date-stage-independent")
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    entered_without_transaction: list[bool] = []

    def settle(session: Session) -> None:
        entered_without_transaction.append(not session.in_transaction())

    settle.requires_independent_sessions = True

    result = run_daily_stages(
        factory,
        job_id="date-stage-independent",
        handlers={"settle": settle},
        stage_order=("settle",),
    )

    assert result.completed_stages == ("settle",)
    assert entered_without_transaction == [True]


def test_refund_collector_failure_isolated_to_one_date_and_retryable(
    db_session: Session,
) -> None:
    _seed_job(db_session, "date-refund-fails")
    _seed_job(
        db_session,
        "date-refund-untouched",
        business_date=date(2026, 8, 6),
    )
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, future=True)
    source_window = CollectionWindow(
        start=datetime(2026, 8, 5, tzinfo=UTC),
        end=datetime(2026, 8, 6, tzinfo=UTC),
        timezone_name="Asia/Shanghai",
    )

    class BrokenRefundClient:
        def iter_refunds(self, *_args, **_kwargs):
            raise RefundCollectionError("refund source unavailable")

    def failed_collect(session: Session) -> None:
        collect_refunds(
            session,
            BrokenRefundClient(),
            source_window,
            source_run_id="date-refund-fails",
        )

    with pytest.raises(RefundCollectionError, match="source unavailable"):
        run_daily_stages(
            factory,
            job_id="date-refund-fails",
            handlers={"collect": failed_collect},
        )

    with factory() as verify:
        failed_stage = verify.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == "date-refund-fails",
                JobStageRun.stage_name == "collect",
            )
        )
        untouched_stage = verify.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == "date-refund-untouched",
                JobStageRun.stage_name == "collect",
            )
        )
        assert failed_stage is not None and failed_stage.status == "failed"
        assert untouched_stage is None

    calls: list[str] = []

    def retry_collect(_session: Session) -> None:
        calls.append("refunds")

    result = run_daily_stages(
        factory,
        job_id="date-refund-fails",
        handlers={"collect": retry_collect},
    )
    assert result.status == "success"
    assert calls == ["refunds"]
