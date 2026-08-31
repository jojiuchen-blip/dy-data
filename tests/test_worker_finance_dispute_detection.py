from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import session_scope
from apps.api.dy_api import finance_dispute_detection
from apps.api.dy_api.models import (
    Base,
    DimStore,
    JobRun,
    SettlementDispute,
    SettlementDisputeOrder,
    SettlementStatement,
    SettlementStatementEntry,
)
from apps.worker import queued_jobs, scheduler
from apps.worker.queued_jobs import (
    process_queued_finance_dispute_detections,
)


def _factory(db_session: Session) -> sessionmaker[Session]:
    return sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        future=True,
    )


def _seed_detection_scope(
    session: Session,
    *,
    suffix: str,
) -> tuple[str, str]:
    store_id = f"worker-store-{suffix}"
    statement_id = f"worker-statement-{suffix}"
    dispute_id = f"worker-dispute-{suffix}"
    order_id = f"worker-order-{suffix}"
    coupon_id = f"worker-coupon-{suffix}"
    session.add_all(
        [
            DimStore(
                store_id=store_id,
                store_name=f"Worker Store {suffix}",
                is_active=True,
            ),
            SettlementStatement(
                statement_id=statement_id,
                store_id=store_id,
                statement_month="2026-08",
                version_no=1,
                is_current=True,
                statement_status=4,
                promotion_original_fee_cent=100,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=100,
                management_original_fee_cent=0,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=0,
            ),
            SettlementStatementEntry(
                statement_entry_id=f"worker-entry-{suffix}",
                statement_id=statement_id,
                statement_line_id=f"worker-line-{suffix}",
                source_type=1,
                source_record_id=f"worker-source-{suffix}",
                original_fee_result_id=f"worker-fee-{suffix}",
                order_id=order_id,
                coupon_id=coupon_id,
                fee_direction=1,
                original_business_month="2026-08",
                statement_posting_month="2026-08",
                product_scope="LOCAL_LIFE",
                product_type="SERVICE_PRODUCT",
                base_amount_cent=1000,
                fee_amount_cent=100,
                rule_version="worker-rule-v1",
            ),
            SettlementDispute(
                dispute_id=dispute_id,
                statement_id=statement_id,
                store_id=store_id,
                statement_month="2026-08",
                fee_direction=1,
                dispute_type=3,
                status=1,
                disputed_amount_cent=100,
                description="worker consistency detection",
                contact_name="worker contact",
                contact_phone_ciphertext="invalid-test-ciphertext",
                evidence_json=[],
                submitted_by="worker-store-user",
            ),
            SettlementDisputeOrder(
                dispute_id=dispute_id,
                order_id=order_id,
                coupon_id=coupon_id,
                disputed_amount_cent=100,
            ),
        ]
    )
    return dispute_id, statement_id


def _queue_detection(
    session: Session,
    *,
    job_id: str,
    dispute_id: str,
    started_at: datetime,
) -> None:
    session.add(
        JobRun(
            job_id=job_id,
            job_name="finance_dispute_detection",
            status="queued",
            started_at=started_at,
            success_count=0,
            failed_count=0,
            metadata_json={
                "disputeId": dispute_id,
                "requestedBy": "system-admin",
                "progress": 0,
                "result": None,
                "failureReason": None,
                "attemptCount": 0,
            },
        )
    )


def test_worker_executes_persisted_finance_detection_without_api_background(
    db_session: Session,
) -> None:
    dispute_id, _ = _seed_detection_scope(db_session, suffix="actual")
    _queue_detection(
        db_session,
        job_id="worker-detection-actual",
        dispute_id=dispute_id,
        started_at=datetime(2026, 8, 30, 1, tzinfo=timezone.utc),
    )
    db_session.commit()

    result = process_queued_finance_dispute_detections(
        _factory(db_session),
        now=datetime(2026, 8, 30, 2, tzinfo=timezone.utc),
    )

    db_session.expire_all()
    job = db_session.get(JobRun, "worker-detection-actual")
    assert result.processed_job_ids == ("worker-detection-actual",)
    assert job is not None
    assert job.status == "succeeded"
    assert job.finished_at is not None
    assert job.metadata_json["attemptCount"] == 1
    assert job.metadata_json["progress"] == 100
    assert job.metadata_json["result"]["consistencyStatus"] == "CONSISTENT"
    assert job.metadata_json["stage"] == "COMPLETED"
    assert job.state_updated_at == job.finished_at


def test_finance_detection_claim_prevents_two_workers_from_executing_same_job(
    db_session: Session,
    monkeypatch,
) -> None:
    now = datetime(2026, 8, 30, 2, tzinfo=timezone.utc)
    _queue_detection(
        db_session,
        job_id="worker-detection-claim",
        dispute_id="claim-only-dispute",
        started_at=now,
    )
    db_session.commit()
    factory = _factory(db_session)
    calls: list[tuple[str, str]] = []
    nested_results = []

    def fake_runner(*, job_id: str, session_factory, claim_id: str) -> None:
        calls.append((job_id, claim_id))
        nested_results.append(
            process_queued_finance_dispute_detections(
                factory,
                now=now,
                max_jobs=1,
            )
        )
        with session_scope(factory) as session:
            job = session.get(JobRun, job_id)
            assert job is not None
            job.status = "succeeded"
            job.success_count = 1
            job.finished_at = now
            job.metadata_json = {
                **job.metadata_json,
                "progress": 100,
                "result": {"consistencyStatus": "CONSISTENT"},
            }

    monkeypatch.setattr(
        queued_jobs,
        "run_finance_dispute_detection_job",
        fake_runner,
    )

    result = process_queued_finance_dispute_detections(
        factory,
        now=now,
        max_jobs=1,
    )

    assert result.processed_job_ids == ("worker-detection-claim",)
    assert len(calls) == 1
    assert nested_results[0].processed_job_ids == ()


def test_stale_claimant_cannot_complete_after_new_claim_owns_job(
    tmp_path,
    monkeypatch,
) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'finance-claim-fence.sqlite').as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    with session_scope(factory) as session:
        dispute_id, _ = _seed_detection_scope(session, suffix="claim-fence")
        _queue_detection(
            session,
            job_id="worker-detection-claim-fence",
            dispute_id=dispute_id,
            started_at=datetime(2026, 8, 30, 1, tzinfo=timezone.utc),
        )
    with session_scope(factory) as session:
        assert finance_dispute_detection.claim_finance_dispute_detection_job(
            session,
            job_id="worker-detection-claim-fence",
            claim_id="claim-a",
            claimed_at=datetime(2026, 8, 30, 2, tzinfo=timezone.utc),
        )

    def reclaim_during_evaluation(session, dispute):
        with session_scope(factory) as recovery_session:
            job = recovery_session.get(JobRun, "worker-detection-claim-fence")
            assert job is not None
            job.status = "queued"
            job.claim_token = None
            job.lease_expires_at = None
            job.metadata_json = {
                **job.metadata_json,
                "claimId": None,
                "claimedAt": None,
                "stage": "RETRY_QUEUED",
            }
        with session_scope(factory) as new_claim_session:
            assert finance_dispute_detection.claim_finance_dispute_detection_job(
                new_claim_session,
                job_id="worker-detection-claim-fence",
                claim_id="claim-b",
                claimed_at=datetime(2026, 8, 30, 2, 6, tzinfo=timezone.utc),
            )
        return {
            "consistencyStatus": "CONSISTENT",
            "checks": {"oldClaimMustNotWin": True},
            "evidence": [],
        }

    monkeypatch.setattr(
        finance_dispute_detection,
        "_evaluate_dispute_consistency",
        reclaim_during_evaluation,
    )
    finance_dispute_detection.run_finance_dispute_detection_job(
        job_id="worker-detection-claim-fence",
        session_factory=factory,
        claim_id="claim-a",
    )

    with factory() as session:
        job = session.get(JobRun, "worker-detection-claim-fence")
        assert job is not None
        assert job.status == "running"
        assert job.claim_token == "claim-b"
        assert job.metadata_json["claimId"] == "claim-b"
        assert job.metadata_json.get("result") is None


def test_failed_detection_preserves_last_real_progress_and_persisted_stage(
    db_session: Session,
    monkeypatch,
) -> None:
    dispute_id, _ = _seed_detection_scope(db_session, suffix="failed-progress")
    _queue_detection(
        db_session,
        job_id="worker-detection-failed-progress",
        dispute_id=dispute_id,
        started_at=datetime(2026, 8, 30, 1, tzinfo=timezone.utc),
    )
    db_session.commit()
    factory = _factory(db_session)

    def fail_after_first_heartbeat(session, dispute):
        raise RuntimeError("controlled detection failure")

    monkeypatch.setattr(
        finance_dispute_detection,
        "_evaluate_dispute_consistency",
        fail_after_first_heartbeat,
    )
    finance_dispute_detection.run_finance_dispute_detection_job(
        job_id="worker-detection-failed-progress",
        session_factory=factory,
    )

    db_session.expire_all()
    failed = db_session.get(JobRun, "worker-detection-failed-progress")
    assert failed is not None
    assert failed.status == "failed"
    assert failed.metadata_json["progress"] == 10
    assert failed.metadata_json["stage"] == "FAILED"
    assert failed.finished_at is not None
    assert failed.state_updated_at == failed.finished_at


def test_stale_finance_detection_is_retried_then_failed_after_attempt_limit(
    db_session: Session,
    monkeypatch,
) -> None:
    now = datetime(2026, 8, 30, 2, tzinfo=timezone.utc)
    stale_at = now - timedelta(minutes=10)
    db_session.add_all(
        [
            JobRun(
                job_id="worker-detection-retry",
                job_name="finance_dispute_detection",
                status="running",
                started_at=stale_at,
                success_count=0,
                failed_count=0,
                metadata_json={
                    "disputeId": "retry-dispute",
                    "progress": 40,
                    "attemptCount": 1,
                    "claimId": "dead-worker-1",
                    "claimedAt": stale_at.isoformat(),
                },
            ),
            JobRun(
                job_id="worker-detection-exhausted",
                job_name="finance_dispute_detection",
                status="running",
                started_at=stale_at,
                success_count=0,
                failed_count=0,
                metadata_json={
                    "disputeId": "exhausted-dispute",
                    "progress": 40,
                    "attemptCount": 2,
                    "claimId": "dead-worker-2",
                    "claimedAt": stale_at.isoformat(),
                },
            ),
        ]
    )
    db_session.commit()
    factory = _factory(db_session)
    calls: list[str] = []

    def fake_runner(*, job_id: str, session_factory, claim_id: str) -> None:
        calls.append(job_id)
        with session_scope(factory) as session:
            job = session.get(JobRun, job_id)
            assert job is not None
            job.status = "succeeded"
            job.success_count = 1
            job.finished_at = now
            job.metadata_json = {**job.metadata_json, "progress": 100}

    monkeypatch.setattr(
        queued_jobs,
        "run_finance_dispute_detection_job",
        fake_runner,
    )

    result = process_queued_finance_dispute_detections(
        factory,
        now=now,
        stale_after=timedelta(minutes=5),
        max_attempts=2,
    )

    db_session.expire_all()
    retried = db_session.get(JobRun, "worker-detection-retry")
    exhausted = db_session.get(JobRun, "worker-detection-exhausted")
    assert result.recovered_job_ids == ("worker-detection-retry",)
    assert result.failed_stale_job_ids == ("worker-detection-exhausted",)
    assert result.processed_job_ids == ("worker-detection-retry",)
    assert calls == ["worker-detection-retry"]
    assert retried is not None
    assert retried.status == "succeeded"
    assert retried.metadata_json["attemptCount"] == 2
    assert exhausted is not None
    assert exhausted.status == "failed"
    assert exhausted.failed_count == 1
    assert exhausted.finished_at is not None
    assert exhausted.metadata_json["progress"] == 40
    assert exhausted.metadata_json["stage"] == "FAILED"
    assert "重试次数" in exhausted.metadata_json["failureReason"]


def test_stale_recovery_does_not_override_a_concurrent_heartbeat(tmp_path) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'finance-recovery-cas.sqlite').as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    standard_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    now = datetime(2026, 8, 30, 2, tzinfo=timezone.utc)
    stale_at = now - timedelta(minutes=10)
    heartbeat_at = now - timedelta(minutes=1)
    with session_scope(standard_factory) as session:
        session.add(
            JobRun(
                job_id="worker-detection-heartbeat-race",
                job_name="finance_dispute_detection",
                status="running",
                started_at=stale_at,
                success_count=0,
                failed_count=0,
                claim_token="live-worker",
                lease_expires_at=stale_at + timedelta(minutes=5),
                state_updated_at=stale_at,
                metadata_json={
                    "disputeId": "heartbeat-race-dispute",
                    "progress": 10,
                    "attemptCount": 1,
                    "claimId": "live-worker",
                    "claimedAt": stale_at.isoformat(),
                    "stage": "EVALUATING_CONSISTENCY",
                },
            )
        )

    race = {"triggered": False}

    class HeartbeatRaceSession(Session):
        def scalars(self, statement, *args, **kwargs):
            rows = list(super().scalars(statement, *args, **kwargs))
            if not race["triggered"] and rows:
                with session_scope(standard_factory) as heartbeat_session:
                    current = heartbeat_session.get(
                        JobRun, "worker-detection-heartbeat-race"
                    )
                    assert current is not None
                    heartbeat_session.execute(
                        update(JobRun)
                        .where(
                            JobRun.job_id == current.job_id,
                            JobRun.claim_token == "live-worker",
                        )
                        .values(
                            state_updated_at=heartbeat_at,
                            lease_expires_at=heartbeat_at + timedelta(minutes=5),
                            metadata_json={
                                **current.metadata_json,
                                "progress": 20,
                                "stage": "EVALUATING_CONSISTENCY",
                            },
                        )
                    )
                race["triggered"] = True
            return iter(rows)

    recovery_factory = sessionmaker(
        bind=engine,
        class_=HeartbeatRaceSession,
        autoflush=False,
        autocommit=False,
        future=True,
    )

    recovered, failed = queued_jobs._recover_stale_finance_detections(
        recovery_factory,
        now=now,
        stale_after=timedelta(minutes=5),
        max_attempts=2,
    )

    with standard_factory() as session:
        current = session.get(JobRun, "worker-detection-heartbeat-race")
        assert current is not None
        assert recovered == []
        assert failed == []
        assert current.status == "running"
        assert current.claim_token == "live-worker"
        assert current.state_updated_at is not None
        assert current.state_updated_at.replace(tzinfo=timezone.utc) == heartbeat_at
        assert current.metadata_json["progress"] == 20


def test_detection_failure_does_not_override_a_reclaimed_job(
    tmp_path,
    monkeypatch,
) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'finance-failure-cas.sqlite').as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    standard_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    claimed_at = datetime(2026, 8, 30, 2, tzinfo=timezone.utc)
    reclaimed_at = claimed_at + timedelta(minutes=6)
    with session_scope(standard_factory) as session:
        dispute_id, _ = _seed_detection_scope(session, suffix="failure-race")
        _queue_detection(
            session,
            job_id="worker-detection-failure-race",
            dispute_id=dispute_id,
            started_at=claimed_at,
        )
    with session_scope(standard_factory) as session:
        assert finance_dispute_detection.claim_finance_dispute_detection_job(
            session,
            job_id="worker-detection-failure-race",
            claim_id="claim-a",
            claimed_at=claimed_at,
        )

    gets = {"count": 0, "reclaimed": False}

    class FailureRaceSession(Session):
        def get(self, entity, ident, *args, **kwargs):
            row = super().get(entity, ident, *args, **kwargs)
            if entity is JobRun and ident == "worker-detection-failure-race":
                gets["count"] += 1
                if gets["count"] == 2 and not gets["reclaimed"]:
                    with session_scope(standard_factory) as reclaim_session:
                        current = reclaim_session.get(JobRun, ident)
                        assert current is not None
                        reclaim_session.execute(
                            update(JobRun)
                            .where(
                                JobRun.job_id == ident,
                                JobRun.claim_token == "claim-a",
                            )
                            .values(
                                status="running",
                                claim_token="claim-b",
                                state_updated_at=reclaimed_at,
                                lease_expires_at=reclaimed_at + timedelta(minutes=5),
                                metadata_json={
                                    **current.metadata_json,
                                    "claimId": "claim-b",
                                    "claimedAt": reclaimed_at.isoformat(),
                                    "stage": "CLAIMED",
                                },
                            )
                        )
                    gets["reclaimed"] = True
            return row

    failure_factory = sessionmaker(
        bind=engine,
        class_=FailureRaceSession,
        autoflush=False,
        autocommit=False,
        future=True,
    )

    def fail_after_heartbeat(session, dispute):
        raise RuntimeError("force failure after heartbeat")

    monkeypatch.setattr(
        finance_dispute_detection,
        "_evaluate_dispute_consistency",
        fail_after_heartbeat,
    )
    finance_dispute_detection.run_finance_dispute_detection_job(
        job_id="worker-detection-failure-race",
        session_factory=failure_factory,
        claim_id="claim-a",
    )

    with standard_factory() as session:
        current = session.get(JobRun, "worker-detection-failure-race")
        assert current is not None
        assert gets["reclaimed"] is True
        assert current.status == "running"
        assert current.claim_token == "claim-b"
        assert current.metadata_json["claimId"] == "claim-b"
        assert current.metadata_json.get("failureReason") is None


def test_scheduler_run_once_scans_finance_detection_queue(
    db_session: Session,
    monkeypatch,
) -> None:
    factory = _factory(db_session)
    calls: list[str] = []
    monkeypatch.setenv("WORKER_MODE", "settlement_only")
    monkeypatch.setattr(scheduler, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        scheduler,
        "process_queued_settlement_rebuilds",
        lambda factory_arg: calls.append("settlement-queue"),
    )
    monkeypatch.setattr(
        scheduler,
        "process_queued_finance_dispute_detections",
        lambda factory_arg: calls.append("finance-detection-queue"),
        raising=False,
    )
    monkeypatch.setattr(
        scheduler,
        "run_settlement_job",
        lambda session, *, job_id, source_run_id: calls.append("settlement-run"),
    )

    scheduler.run_once()

    assert calls == [
        "settlement-queue",
        "finance-detection-queue",
        "settlement-run",
    ]
