from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    JobEvent,
    JobRun,
    JobStageRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
)
from apps.worker import finalize
from apps.worker.daily_windows import enqueue_finalize_if_ready, plan_daily_sync
from apps.worker.legacy_projection_bootstrap import (
    ResourceGateConfig,
    certify_legacy_null_root,
)
from apps.worker.projection_lineage import resolve_projection_partitions
from apps.worker.stage_runner import run_daily_stages
from apps.worker.task_control import claim_job, complete_job


def _factory(session: Session) -> sessionmaker[Session]:
    return sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def _seed_base(
    session: Session,
    *,
    prefix: str,
    legacy_months: tuple[str, ...] = (),
) -> str:
    base_generation_id = f"{prefix}-base"
    session.add(
        SettlementProjectionGeneration(
            generation_id=base_generation_id,
            base_generation_id=None,
            generation_kind="legacy_root",
            compaction_base_generation_id=None,
            projection_name="settlement",
            state="published",
            input_fingerprint=(prefix.encode("utf-8").hex() + "0" * 64)[:64],
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
    session.flush()
    session.add(
        SettlementProjectionActive(
            projection_name="settlement",
            generation_id=base_generation_id,
        )
    )
    for index, month in enumerate(legacy_months, start=1):
        session.add(
            AggStoreMonthlySettlement(
                month=month,
                store_id=f"{prefix}-legacy-store",
                product_scope="all",
                product_type="all",
                sales_order_count=1,
                sales_amount_cent=100 * index,
                verified_order_count=1,
                verified_amount_cent=80 * index,
                promotion_base_cent=100 * index,
                promotion_original_fee_cent=10 * index,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=10 * index,
                management_base_cent=80 * index,
                management_original_fee_cent=4 * index,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=4 * index,
                statement_status=1,
                projection_run_id=f"{prefix}-legacy-run",
            )
        )
    session.flush()
    return base_generation_id


def _complete_prerequisites(
    session: Session,
    *,
    parent_job_id: str,
    affected_months: tuple[str, ...],
    affected_store_ids: tuple[str, ...] = (),
) -> None:
    now = datetime(2026, 8, 9, 1, 0, tzinfo=UTC)
    children = list(
        session.scalars(
            select(JobRun)
            .where(
                JobRun.parent_job_id == parent_job_id,
                JobRun.job_kind == "date_sync",
            )
            .order_by(JobRun.business_date, JobRun.job_id)
        )
    )
    changed = bool(affected_months or affected_store_ids)
    for child in children:
        child.status = "success"
        summary = {
            "mode": "incremental",
            "completed": True,
            "impact_count": 1 if changed else 0,
            "coupon_count": 1 if changed else 0,
            "detail_count": 1 if changed else 0,
            "result_count": 1 if changed else 0,
            "adjustment_count": 0,
            "last_impact_id": 1 if changed else None,
            "affected_months": list(affected_months),
            "affected_store_ids": list(affected_store_ids),
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
                        "affected_store_ids": list(affected_store_ids),
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


def _prepare_finalize(
    session: Session,
    *,
    prefix: str,
    affected_months: tuple[str, ...],
) -> tuple[sessionmaker[Session], str, str, object, finalize.FenceToken, str]:
    base_generation_id = _seed_base(
        session,
        prefix=prefix,
        legacy_months=("2026-09",) if affected_months else (),
    )
    plan = plan_daily_sync(
        session,
        start=date(2026, 8, 1),
        end=date(2026, 8, 2),
        target="settlement",
        requested_by="recovery-test",
        trigger_source="manual",
    )
    _complete_prerequisites(
        session,
        parent_job_id=plan.parent_job_id,
        affected_months=affected_months,
    )
    job = enqueue_finalize_if_ready(session, plan.parent_job_id)
    assert job is not None
    token = claim_job(
        session,
        job_id=job.job_id,
        lease_owner=f"{prefix}-owner",
        component_instance_id=f"{prefix}-component",
        lease_seconds=120,
    )
    assert token is not None
    session.commit()
    factory = _factory(session)
    with factory() as fresh:
        finalize_job = fresh.get(JobRun, job.job_id)
        assert finalize_job is not None
        fence_token = finalize.FenceToken.from_job(finalize_job, token)
    return (
        factory,
        plan.parent_job_id,
        job.job_id,
        token,
        fence_token,
        base_generation_id,
    )


def _finalize_handler(
    factory: sessionmaker[Session],
    *,
    parent_job_id: str,
    fence_token: finalize.FenceToken,
):
    def handler(_session: Session, _job: JobRun):
        return finalize.run_finalize_stage(
            factory,
            parent_job_id=parent_job_id,
            fence_token=fence_token,
            batch_size=2,
        )

    handler.requires_independent_sessions = True
    return handler


def test_crash_after_finalize_commit_reuses_manifest_and_once_event(
    db_session: Session,
) -> None:
    (
        factory,
        parent_job_id,
        finalize_job_id,
        token,
        fence_token,
        base_generation_id,
    ) = _prepare_finalize(
        db_session,
        prefix="recovery-crash",
        affected_months=("2026-08",),
    )
    handler = _finalize_handler(
        factory,
        parent_job_id=parent_job_id,
        fence_token=fence_token,
    )

    class SimulatedCrash(RuntimeError):
        pass

    def crash_after_commit(stage_name: str) -> None:
        assert stage_name == "finalize"
        raise SimulatedCrash("process stopped after durable finalize commit")

    with pytest.raises(SimulatedCrash, match="durable finalize commit"):
        run_daily_stages(
            factory,
            job_id=finalize_job_id,
            handlers={"finalize": handler},
            stage_order=("finalize",),
            lease_owner=token.lease_owner,
            lease_epoch=token.lease_epoch,
            attempt_id=token.attempt_id,
            component_instance_id=token.component_instance_id,
            after_stage_commit=crash_after_commit,
        )

    with factory() as session:
        active = session.get(SettlementProjectionActive, "settlement")
        assert active is not None and active.generation_id != base_generation_id
        generation_id = active.generation_id
        generation = session.get(SettlementProjectionGeneration, generation_id)
        assert generation is not None and generation.state == "published"
        manifest_snapshot = tuple(
            (
                row.artifact,
                row.partition_key,
                row.owner_state,
                row.source_kind,
                row.checksum,
            )
            for row in session.scalars(
                select(SettlementProjectionPartitionManifest)
                .where(
                    SettlementProjectionPartitionManifest.generation_id
                    == generation_id
                )
                .order_by(
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                )
            )
        )
        assert ("monthly", "2026-08", "tombstone", "tombstone") in {
            row[:4] for row in manifest_snapshot
        }
        resolved = resolve_projection_partitions(
            session,
            artifact="monthly",
            partition_keys=("2026-08", "2026-09"),
            pinned_generation_id=generation_id,
        )
        assert resolved["2026-08"].source_kind == "tombstone"
        assert resolved["2026-09"].source_kind == "legacy_root"
        assert session.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(
                JobEvent.job_id == finalize_job_id,
                JobEvent.event_type == "settlement_projection_published",
            )
        ) == 1

    retry = run_daily_stages(
        factory,
        job_id=finalize_job_id,
        handlers={"finalize": handler},
        stage_order=("finalize",),
        lease_owner=token.lease_owner,
        lease_epoch=token.lease_epoch,
        attempt_id=token.attempt_id,
        component_instance_id=token.component_instance_id,
    )
    assert retry.completed_stages == ()
    assert retry.skipped_stages == ("finalize",)

    with factory() as session:
        assert tuple(
            (
                row.artifact,
                row.partition_key,
                row.owner_state,
                row.source_kind,
                row.checksum,
            )
            for row in session.scalars(
                select(SettlementProjectionPartitionManifest)
                .where(
                    SettlementProjectionPartitionManifest.generation_id
                    == generation_id
                )
                .order_by(
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                )
            )
        ) == manifest_snapshot
        assert session.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(
                JobEvent.job_id == finalize_job_id,
                JobEvent.event_type == "settlement_projection_published",
            )
        ) == 1

    with factory() as session:
        assert complete_job(session, token, success_count=1) is True
        session.commit()
    with factory() as session:
        assert session.get(JobRun, finalize_job_id).status == "success"
        assert session.get(JobRun, parent_job_id).status == "success"
        assert finalize.reconcile_finalize_parents(session) == 1


def test_reconcile_ignores_completed_parent_after_newer_publication(
    db_session: Session,
) -> None:
    (
        factory,
        parent_job_id,
        finalize_job_id,
        token,
        fence_token,
        _,
    ) = _prepare_finalize(
        db_session,
        prefix="recovery-historical-parent",
        affected_months=(),
    )
    handler = _finalize_handler(
        factory,
        parent_job_id=parent_job_id,
        fence_token=fence_token,
    )
    run_daily_stages(
        factory,
        job_id=finalize_job_id,
        handlers={"finalize": handler},
        stage_order=("finalize",),
        lease_owner=token.lease_owner,
        lease_epoch=token.lease_epoch,
        attempt_id=token.attempt_id,
        component_instance_id=token.component_instance_id,
    )
    with factory() as session:
        assert complete_job(session, token, success_count=1) is True
        session.commit()

    with factory() as session:
        active = session.get(SettlementProjectionActive, "settlement")
        assert active is not None
        previous_generation_id = active.generation_id
        previous = session.get(SettlementProjectionGeneration, previous_generation_id)
        assert previous is not None and previous.state == "published"
        successor_generation_id = "recovery-historical-parent-successor"
        session.add(
            SettlementProjectionGeneration(
                generation_id=successor_generation_id,
                base_generation_id=previous_generation_id,
                generation_kind="lineage",
                compaction_base_generation_id=None,
                projection_name="settlement",
                state="published",
                input_fingerprint="a" * 64,
                lineage_depth=int(previous.lineage_depth or 0) + 1,
                estimated_write_rows=0,
                estimated_write_bytes=0,
                estimated_wal_bytes=0,
                estimated_disk_headroom_bytes=0,
                checkpoint_json={"phase": "published"},
                last_key=None,
                manifest_checksum="b" * 64,
                source_input_json={},
                published_at=datetime.now(UTC),
            )
        )
        active.generation_id = successor_generation_id
        session.commit()

    with factory() as session:
        assert finalize.reconcile_finalize_parents(session) == 0
        assert session.get(JobRun, parent_job_id).status == "success"
        active = session.get(SettlementProjectionActive, "settlement")
        assert active is not None and active.generation_id == successor_generation_id


def test_frozen_settle_fence_drift_is_zero_publication(db_session: Session) -> None:
    (
        factory,
        parent_job_id,
        finalize_job_id,
        token,
        fence_token,
        base_generation_id,
    ) = _prepare_finalize(
        db_session,
        prefix="recovery-fence",
        affected_months=(),
    )
    with factory() as session:
        settle = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == fence_token.settle_stages[0].job_id,
                JobStageRun.stage_name == "settle",
            )
        )
        assert settle is not None
        settle.lease_epoch = int(settle.lease_epoch or 0) + 1
        session.commit()

    with pytest.raises(RuntimeError, match="fence|changed"):
        finalize.run_finalize_stage(
            factory,
            parent_job_id=parent_job_id,
            fence_token=fence_token,
            batch_size=2,
        )

    with factory() as session:
        active = session.get(SettlementProjectionActive, "settlement")
        assert active is not None and active.generation_id == base_generation_id
        assert session.scalar(
            select(func.count())
            .select_from(SettlementProjectionGeneration)
            .where(SettlementProjectionGeneration.generation_kind == "lineage")
        ) == 0
        assert session.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(JobEvent.job_id == finalize_job_id)
        ) == 0
        assert session.get(JobRun, parent_job_id).status != "success"
        assert session.get(JobRun, finalize_job_id).status == "running"
        with pytest.raises(RuntimeError, match="publication stage is incomplete"):
            complete_job(session, token)


def test_resource_guard_precedes_legacy_root_metadata_writes(
    db_session: Session,
) -> None:
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="resource-store",
            product_scope="all",
            product_type="all",
            statement_status=1,
            projection_run_id="resource-run",
        )
    )
    db_session.commit()
    result = certify_legacy_null_root(
        _factory(db_session),
        batch_size=1,
        resource_limits=ResourceGateConfig(
            max_manifest_rows=0,
            max_estimated_write_bytes=1_000_000,
            max_estimated_wal_bytes=2_000_000,
            observed_disk_headroom_bytes=4_000_000,
            min_disk_headroom_bytes=0,
        ),
    )
    assert result.status == "resource_guard"
    assert result.failure_code == "manifest_rows_exceed_limit"
    assert db_session.scalar(
        select(func.count()).select_from(SettlementProjectionGeneration)
    ) == 0
    assert db_session.scalar(
        select(func.count()).select_from(SettlementProjectionPartitionManifest)
    ) == 0
    assert db_session.get(SettlementProjectionActive, "settlement") is None
