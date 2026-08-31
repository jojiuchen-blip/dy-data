"""Dedicated PostgreSQL integration gate for settlement finalize recovery.

Only ``DYDATA_T12_TEST_DATABASE_URL`` is read.  Every test uses a disposable,
random schema and drops only that validated schema during teardown.
"""

from __future__ import annotations

import os
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.db import normalize_database_url
from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    Base,
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


POSTGRES_ENV_NAME = "DYDATA_T12_TEST_DATABASE_URL"
POSTGRES_URL = os.getenv(POSTGRES_ENV_NAME)
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason=f"set {POSTGRES_ENV_NAME} to the dedicated disposable PostgreSQL database",
)
_SCHEMA_PATTERN = re.compile(r"t34_gate_[0-9a-f]{12}\Z")


def _validated_postgres_url(raw_url: str) -> URL:
    url = make_url(normalize_database_url(raw_url))
    if not url.drivername.startswith("postgresql+"):
        raise RuntimeError("T3.4 gate requires a PostgreSQL driver")
    if url.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("T3.4 PostgreSQL gate requires a loopback host")
    if url.port != 15432:
        raise RuntimeError("T3.4 PostgreSQL gate requires dedicated port 15432")
    if url.database != "dydata_t12" or url.username != "dydata_t12":
        raise RuntimeError("T3.4 PostgreSQL gate identity is not dedicated")
    if not url.password and not os.getenv("PGPASSWORD"):
        raise RuntimeError("T3.4 PostgreSQL gate password is missing")
    return url


@pytest.fixture()
def postgres_stack() -> tuple[object, sessionmaker[Session]]:
    assert POSTGRES_URL is not None
    url = _validated_postgres_url(POSTGRES_URL)
    schema = f"t34_gate_{secrets.token_hex(6)}"
    assert _SCHEMA_PATTERN.fullmatch(schema)
    admin_engine = create_engine(url, future=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={
            "options": (
                f"-c search_path={schema} "
                "-c lock_timeout=5000 -c statement_timeout=30000"
            )
        },
        pool_pre_ping=True,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    try:
        with factory() as session:
            assert session.scalar(text("SELECT current_schema()")) == schema
            assert session.scalar(text("SHOW transaction_isolation")) == "read committed"
        yield engine, factory
    finally:
        engine.dispose()
        if _SCHEMA_PATTERN.fullmatch(schema):
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


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
    affected_months: tuple[str, ...] = (),
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
    changed = bool(affected_months)
    for child in children:
        child.status = "success"
        session.add(
            JobStageRun(
                stage_run_id=f"stage-{child.job_id}-settle",
                job_id=child.job_id,
                stage_name="settle",
                status="success",
                checkpoint_json={
                    "settlement_summary": {
                        "mode": "incremental",
                        "completed": True,
                        "impact_count": 1 if changed else 0,
                        "coupon_count": 1 if changed else 0,
                        "detail_count": 1 if changed else 0,
                        "result_count": 1 if changed else 0,
                        "adjustment_count": 0,
                        "last_impact_id": 1 if changed else None,
                        "affected_months": list(affected_months),
                        "affected_store_ids": [],
                    },
                    "store_score_snapshot": {
                        "deferred": True,
                        "consumer": "T3.4.finalize",
                        "affected_store_ids": [],
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


def _enqueue_finalize(
    factory: sessionmaker[Session],
    *,
    prefix: str,
    affected_months: tuple[str, ...] = (),
) -> tuple[str, str, str]:
    with factory.begin() as session:
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
            requested_by="postgres-gate",
            trigger_source="manual",
        )
        _complete_prerequisites(
            session,
            parent_job_id=plan.parent_job_id,
            affected_months=affected_months,
        )
        job = enqueue_finalize_if_ready(session, plan.parent_job_id)
        assert job is not None
        return plan.parent_job_id, job.job_id, base_generation_id


def _run_finalize(
    factory: sessionmaker[Session],
    *,
    parent_job_id: str,
    finalize_job_id: str,
    token: object,
    after_stage_commit=None,
):
    with factory() as session:
        job = session.get(JobRun, finalize_job_id)
        assert job is not None
        fence_token = finalize.FenceToken.from_job(job, token)

    def handler(_session: Session, _job: JobRun):
        return finalize.run_finalize_stage(
            factory,
            parent_job_id=parent_job_id,
            fence_token=fence_token,
            batch_size=2,
        )

    handler.requires_independent_sessions = True
    return run_daily_stages(
        factory,
        job_id=finalize_job_id,
        handlers={"finalize": handler},
        stage_order=("finalize",),
        lease_owner=token.lease_owner,
        lease_epoch=token.lease_epoch,
        attempt_id=token.attempt_id,
        component_instance_id=token.component_instance_id,
        after_stage_commit=after_stage_commit,
    )


def test_postgres_active_once_key_and_complete_job_promotion_lock_compete(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    parent_job_id, finalize_job_id, base_generation_id = _enqueue_finalize(
        factory,
        prefix="pg-lock",
    )
    claim_barrier = Barrier(2)

    def claim(owner: str):
        claim_barrier.wait(timeout=10)
        with factory() as session:
            token = claim_job(
                session,
                job_id=finalize_job_id,
                lease_owner=owner,
                component_instance_id=f"{owner}-component",
                lease_seconds=120,
            )
            session.commit()
            return token

    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = [
            pool.submit(claim, "pg-finalize-a"),
            pool.submit(claim, "pg-finalize-b"),
        ]
        claimed = [future.result(timeout=20) for future in tokens]
    winners = [token for token in claimed if token is not None]
    assert len(winners) == 1
    token = winners[0]

    result = _run_finalize(
        factory,
        parent_job_id=parent_job_id,
        finalize_job_id=finalize_job_id,
        token=token,
    )
    assert result.completed_stages == ("finalize",)

    complete_barrier = Barrier(2)

    def complete() -> bool:
        complete_barrier.wait(timeout=10)
        with factory() as session:
            completed = complete_job(session, token, success_count=1)
            session.commit()
            return completed

    with ThreadPoolExecutor(max_workers=2) as pool:
        completions = [pool.submit(complete), pool.submit(complete)]
        complete_results = [future.result(timeout=20) for future in completions]
    assert sorted(complete_results) == [False, True]

    with factory() as session:
        active_rows = list(session.scalars(select(SettlementProjectionActive)))
        assert len(active_rows) == 1
        assert active_rows[0].generation_id != base_generation_id
        active_generation = session.get(
            SettlementProjectionGeneration,
            active_rows[0].generation_id,
        )
        assert active_generation is not None
        assert active_generation.state == "published"
        assert active_generation.base_generation_id == base_generation_id
        assert session.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(
                JobEvent.job_id == finalize_job_id,
                JobEvent.event_type == "settlement_projection_published",
            )
        ) == 1
        assert session.get(JobRun, finalize_job_id).status == "success"
        assert session.get(JobRun, parent_job_id).status == "success"
        parent_stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == parent_job_id,
                JobStageRun.stage_name == "finalize",
            )
        )
        assert parent_stage is not None and parent_stage.status == "success"


def test_postgres_resource_tombstone_lineage_crash_retry(
    postgres_stack: tuple[object, sessionmaker[Session]],
) -> None:
    _engine, factory = postgres_stack
    with factory.begin() as session:
        session.add(
            AggStoreMonthlySettlement(
                month="2026-09",
                store_id="pg-resource-store",
                product_scope="all",
                product_type="all",
                statement_status=1,
                projection_run_id="pg-resource-run",
            )
        )
    guard = certify_legacy_null_root(
        factory,
        batch_size=1,
        resource_limits=ResourceGateConfig(
            max_manifest_rows=0,
            max_estimated_write_bytes=1_000_000,
            max_estimated_wal_bytes=2_000_000,
            observed_disk_headroom_bytes=4_000_000,
            min_disk_headroom_bytes=0,
        ),
    )
    assert guard.status == "resource_guard"
    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(SettlementProjectionGeneration)
        ) == 0
        assert session.get(SettlementProjectionActive, "settlement") is None
        session.query(AggStoreMonthlySettlement).delete()
        session.commit()

    parent_job_id, finalize_job_id, base_generation_id = _enqueue_finalize(
        factory,
        prefix="pg-crash",
        affected_months=("2026-08",),
    )
    with factory() as session:
        token = claim_job(
            session,
            job_id=finalize_job_id,
            lease_owner="pg-crash-owner",
            component_instance_id="pg-crash-component",
            lease_seconds=120,
        )
        session.commit()
    assert token is not None

    class SimulatedCrash(RuntimeError):
        pass

    def crash_after_commit(stage_name: str) -> None:
        assert stage_name == "finalize"
        raise SimulatedCrash("postgres crash after finalize commit")

    with pytest.raises(SimulatedCrash, match="after finalize commit"):
        _run_finalize(
            factory,
            parent_job_id=parent_job_id,
            finalize_job_id=finalize_job_id,
            token=token,
            after_stage_commit=crash_after_commit,
        )

    retry = _run_finalize(
        factory,
        parent_job_id=parent_job_id,
        finalize_job_id=finalize_job_id,
        token=token,
    )
    assert retry.completed_stages == ()
    assert retry.skipped_stages == ("finalize",)

    with factory() as session:
        active = session.get(SettlementProjectionActive, "settlement")
        assert active is not None and active.generation_id != base_generation_id
        resolution = resolve_projection_partitions(
            session,
            artifact="monthly",
            partition_keys=("2026-08", "2026-09"),
            pinned_generation_id=active.generation_id,
        )
        assert resolution["2026-08"].source_kind == "tombstone"
        assert resolution["2026-09"].source_kind == "legacy_root"
        manifests = list(
            session.scalars(
                select(SettlementProjectionPartitionManifest).where(
                    SettlementProjectionPartitionManifest.generation_id
                    == active.generation_id
                )
            )
        )
        assert manifests
        assert any(
            row.artifact == "monthly"
            and row.partition_key == "2026-08"
            and row.owner_state == "tombstone"
            for row in manifests
        )
        assert session.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(
                JobEvent.job_id == finalize_job_id,
                JobEvent.event_type == "settlement_projection_published",
            )
        ) == 1
        assert complete_job(session, token, success_count=1) is True
        session.commit()

    with factory() as session:
        assert session.get(JobRun, parent_job_id).status == "success"
        assert session.get(JobRun, finalize_job_id).status == "success"
