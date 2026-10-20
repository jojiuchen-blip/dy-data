"""Protected publication of a ready settlement compaction head.

Red-first contract for ``publish_settlement_compaction``: the publication must
be a claim-fenced, CAS-guarded, once-audited operation that never relaxes the
lineage-only rules of the existing rebuild publisher.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    JobEvent,
    JobRun,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementProjectionActive,
    SettlementProjectionCompactionClosure,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    SettlementStatement,
)
from apps.worker.legacy_projection_bootstrap import (
    CompactionThresholdConfig,
    compact_projection_metadata,
)
from tests.test_legacy_projection_bootstrap import (
    _factory,
    _limits,
    _seed_task3c_lineage,
)

COMPACTION_JOB_NAME = "settlement_compaction"


def _seed_statement(db_session: Session, prefix: str) -> tuple[str, int, int]:
    db_session.add(
        SettlementStatement(
            statement_id=f"{prefix}-stmt",
            store_id=f"{prefix}-store",
            statement_month="2026-09",
            statement_status=4,
            lock_version=f"{prefix}-lock",
        )
    )
    db_session.flush()
    return f"{prefix}-stmt", 4, 0


def _frozen_snapshot(db_session: Session, statement_id: str) -> dict[str, object]:
    statement = db_session.scalar(
        select(SettlementStatement).where(SettlementStatement.statement_id == statement_id)
    )
    assert statement is not None
    return {
        "statement_tuple": (
            statement.statement_id,
            statement.statement_status,
            statement.statement_month,
            statement.lock_version,
            statement.promotion_net_fee_cent,
            statement.management_net_fee_cent,
        ),
        "statement_count": db_session.scalar(
            select(func.count()).select_from(SettlementStatement)
        ),
        "fee_result_count": db_session.scalar(
            select(func.count()).select_from(SettlementFeeResult)
        ),
        "adjustment_count": db_session.scalar(
            select(func.count()).select_from(SettlementFeeAdjustment)
        ),
    }


def _ready_compact_head(
    db_session: Session, prefix: str
) -> tuple[str, str, str, str]:
    ids = _seed_task3c_lineage(db_session, prefix=prefix)
    result = compact_projection_metadata(
        _factory(db_session),
        base_generation_id=ids["head"],
        threshold_config=CompactionThresholdConfig(minimum_lineage_depth=1, batch_size=2),
        resource_limits=_limits(rows=10),
    )
    assert result.status == "ready"
    assert result.generation_id is not None
    db_session.expire_all()
    compact = db_session.get(SettlementProjectionGeneration, result.generation_id)
    assert compact is not None and compact.manifest_checksum is not None
    assert compact.input_fingerprint is not None
    return (
        ids["head"],
        result.generation_id,
        compact.input_fingerprint,
        compact.manifest_checksum,
    )


def _seed_compaction_job(
    db_session: Session,
    *,
    job_id: str = "job-settlement-compaction-1",
    claim: str = "claim-1",
    status: str = "running",
    lease_seconds: int = 300,
) -> str:
    db_session.add(
        JobRun(
            job_id=job_id,
            job_name=COMPACTION_JOB_NAME,
            status=status,
            started_at=datetime.now(UTC),
            lease_owner="compaction-owner",
            claim_token=claim,
            lease_expires_at=datetime.now(UTC).replace(tzinfo=None)
            + timedelta(seconds=lease_seconds),
            attempt_count=1,
            max_attempts=3,
        )
    )
    db_session.flush()
    return job_id


def test_publishes_ready_compact_head_with_cas_and_audit(db_session: Session) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-pub")
    statement_id, statement_status, statement_total = _seed_statement(db_session, "cmp-pub")
    before = _frozen_snapshot(db_session, statement_id)
    job_id = _seed_compaction_job(db_session)

    payload = publish_settlement_compaction(
        db_session,
        job_id=job_id,
        claim_id="claim-1",
        generation_id=compact_id,
        input_fingerprint=fingerprint,
        manifest_checksum=checksum,
    )
    db_session.flush()

    db_session.expire_all()
    active = db_session.get(SettlementProjectionActive, "settlement")
    compact = db_session.get(SettlementProjectionGeneration, compact_id)
    assert active is not None and active.generation_id == compact_id
    assert compact is not None
    assert compact.state == "published"
    assert compact.published_at is not None
    assert payload == {
        "generation_id": compact_id,
        "input_fingerprint": fingerprint,
        "manifest_checksum": checksum,
        "base_generation_id": head,
        "compaction_protocol": "t342d-metadata-compaction-v1",
    }
    events = list(db_session.scalars(select(JobEvent).where(JobEvent.job_id == job_id)))
    assert len(events) == 1
    assert events[0].event_type == "settlement_projection_published"
    assert events[0].idempotency_key is not None
    assert events[0].idempotency_key.startswith("settlement-compaction-publish-v1:")
    assert events[0].payload_json == payload
    assert events[0].stage_run_id is None
    after = _frozen_snapshot(db_session, statement_id)
    assert after == before


def test_publish_is_idempotent_for_same_claim(db_session: Session) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-idem")
    statement_id, _, _ = _seed_statement(db_session, "cmp-idem")
    before = _frozen_snapshot(db_session, statement_id)
    job_id = _seed_compaction_job(db_session)

    first = publish_settlement_compaction(
        db_session,
        job_id=job_id,
        claim_id="claim-1",
        generation_id=compact_id,
        input_fingerprint=fingerprint,
        manifest_checksum=checksum,
    )
    second = publish_settlement_compaction(
        db_session,
        job_id=job_id,
        claim_id="claim-1",
        generation_id=compact_id,
        input_fingerprint=fingerprint,
        manifest_checksum=checksum,
    )
    db_session.flush()

    assert second == first
    db_session.expire_all()
    active = db_session.get(SettlementProjectionActive, "settlement")
    assert active is not None and active.generation_id == compact_id
    assert (
        db_session.scalar(select(func.count()).select_from(JobEvent).where(JobEvent.job_id == job_id))
        == 1
    )
    assert _frozen_snapshot(db_session, statement_id) == before


def test_publish_refuses_after_active_pointer_moved(db_session: Session) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-move")
    statement_id, _, _ = _seed_statement(db_session, "cmp-move")
    before = _frozen_snapshot(db_session, statement_id)
    job_id = _seed_compaction_job(db_session)

    successor_id = f"cmp-move-after"
    db_session.add(
        SettlementProjectionGeneration(
            generation_id=successor_id,
            base_generation_id=compact_id,
            generation_kind="lineage",
            projection_name="settlement",
            state="published",
            input_fingerprint="d" * 64,
            lineage_depth=1,
            checkpoint_json={},
            manifest_checksum="3" * 64,
            source_input_json={},
            published_at=datetime.now(UTC),
        )
    )
    active = db_session.get(SettlementProjectionActive, "settlement")
    assert active is not None
    active.generation_id = successor_id
    db_session.flush()

    with pytest.raises(RuntimeError, match="active"):
        publish_settlement_compaction(
            db_session,
            job_id=job_id,
            claim_id="claim-1",
            generation_id=compact_id,
            input_fingerprint=fingerprint,
            manifest_checksum=checksum,
        )

    db_session.expire_all()
    active = db_session.get(SettlementProjectionActive, "settlement")
    compact = db_session.get(SettlementProjectionGeneration, compact_id)
    assert active is not None and active.generation_id == successor_id
    assert compact is not None and compact.state == "ready"
    assert db_session.scalar(select(func.count()).select_from(JobEvent)) == 0
    assert _frozen_snapshot(db_session, statement_id) == before


def test_publish_requires_valid_running_claim_and_live_lease(db_session: Session) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-claim")
    statement_id, _, _ = _seed_statement(db_session, "cmp-claim")
    before = _frozen_snapshot(db_session, statement_id)
    job_id = _seed_compaction_job(db_session)
    expired_job_id = _seed_compaction_job(
        db_session,
        job_id="job-settlement-compaction-expired",
        claim="claim-2",
        lease_seconds=-60,
    )
    pending_job_id = _seed_compaction_job(
        db_session,
        job_id="job-settlement-compaction-pending",
        claim="claim-3",
        status="pending",
    )

    def _publish(job: str, claim: str):
        return publish_settlement_compaction(
            db_session,
            job_id=job,
            claim_id=claim,
            generation_id=compact_id,
            input_fingerprint=fingerprint,
            manifest_checksum=checksum,
        )

    with pytest.raises(RuntimeError, match="claim"):
        _publish(job_id, "")
    with pytest.raises(RuntimeError, match="claim"):
        _publish(job_id, "claim-other")
    with pytest.raises(RuntimeError, match="claim"):
        _publish(expired_job_id, "claim-2")
    with pytest.raises(RuntimeError, match="claim"):
        _publish(pending_job_id, "claim-3")

    db_session.expire_all()
    active = db_session.get(SettlementProjectionActive, "settlement")
    compact = db_session.get(SettlementProjectionGeneration, compact_id)
    assert active is not None and active.generation_id == head
    assert compact is not None and compact.state == "ready"
    assert db_session.scalar(select(func.count()).select_from(JobEvent)) == 0
    assert _frozen_snapshot(db_session, statement_id) == before


def test_publish_rejects_tampered_identity_checksum_or_checkpoint(
    db_session: Session,
) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-tamper")
    statement_id, _, _ = _seed_statement(db_session, "cmp-tamper")
    before = _frozen_snapshot(db_session, statement_id)
    job_id = _seed_compaction_job(db_session)

    def _publish(gen: str, fp: str, ck: str):
        return publish_settlement_compaction(
            db_session,
            job_id=job_id,
            claim_id="claim-1",
            generation_id=gen,
            input_fingerprint=fp,
            manifest_checksum=ck,
        )

    with pytest.raises(RuntimeError, match="conflicts"):
        _publish(head, "b" * 64, "1" * 64)
    with pytest.raises(RuntimeError, match="conflicts"):
        _publish(compact_id, fingerprint, "f" * 64)
    with pytest.raises(RuntimeError, match="conflicts"):
        _publish(compact_id, "e" * 64, checksum)

    db_session.expire_all()
    compact = db_session.get(SettlementProjectionGeneration, compact_id)
    assert compact is not None and isinstance(compact.checkpoint_json, dict)
    tampered = dict(compact.checkpoint_json)
    tampered["effective_checksum"] = "0" * 64
    compact.checkpoint_json = tampered
    with pytest.raises(RuntimeError, match="checkpoint"):
        _publish(compact_id, fingerprint, checksum)

    db_session.expire_all()
    compact = db_session.get(SettlementProjectionGeneration, compact_id)
    assert compact is not None and isinstance(compact.checkpoint_json, dict)
    tampered = dict(compact.checkpoint_json)
    tampered["expected_active_pointer"] = "0" * 32 + "9" * 32
    compact.checkpoint_json = tampered
    with pytest.raises(RuntimeError, match="checkpoint"):
        _publish(compact_id, fingerprint, checksum)

    db_session.expire_all()
    active = db_session.get(SettlementProjectionActive, "settlement")
    compact = db_session.get(SettlementProjectionGeneration, compact_id)
    assert active is not None and active.generation_id == head
    assert compact is not None and compact.state == "ready"
    assert db_session.scalar(select(func.count()).select_from(JobEvent)) == 0
    assert _frozen_snapshot(db_session, statement_id) == before


def _assert_refused(
    db_session: Session,
    *,
    head: str,
    compact_id: str,
    statement_id: str,
    snapshot: dict[str, object],
) -> None:
    db_session.expire_all()
    active = db_session.get(SettlementProjectionActive, "settlement")
    compact = db_session.get(SettlementProjectionGeneration, compact_id)
    assert active is not None and active.generation_id == head
    assert compact is not None and compact.state == "ready"
    assert db_session.scalar(select(func.count()).select_from(JobEvent)) == 0
    assert _frozen_snapshot(db_session, statement_id) == snapshot


def test_publish_preserves_caller_pending_rows_across_verification(
    db_session: Session,
) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-txn")
    # Flushed but never committed: both rows live only in the caller's
    # transaction and must survive the savepoint-isolated verification reads.
    db_session.add(
        SettlementStatement(
            statement_id="cmp-txn-stmt",
            store_id="cmp-txn-store",
            statement_month="2026-09",
            statement_status=4,
            lock_version="cmp-txn-lock",
        )
    )
    db_session.add(
        JobRun(
            job_id="job-settlement-compaction-txn",
            job_name=COMPACTION_JOB_NAME,
            status="running",
            started_at=datetime.now(UTC),
            lease_owner="compaction-owner",
            claim_token="claim-txn",
            lease_expires_at=datetime.now(UTC).replace(tzinfo=None)
            + timedelta(seconds=300),
            attempt_count=1,
            max_attempts=3,
        )
    )
    db_session.flush()

    publish_settlement_compaction(
        db_session,
        job_id="job-settlement-compaction-txn",
        claim_id="claim-txn",
        generation_id=compact_id,
        input_fingerprint=fingerprint,
        manifest_checksum=checksum,
    )
    db_session.flush()

    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SettlementStatement)
            .where(SettlementStatement.statement_id == "cmp-txn-stmt")
        )
        == 1
    )
    assert db_session.get(JobRun, "job-settlement-compaction-txn") is not None


def test_publish_follows_caller_transaction_rollback(db_session: Session) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-rbk")
    statement_id, _, _ = _seed_statement(db_session, "cmp-rbk")
    job_id = _seed_compaction_job(
        db_session,
        job_id="job-settlement-compaction-rbk",
        claim="claim-rbk",
    )

    publish_settlement_compaction(
        db_session,
        job_id=job_id,
        claim_id="claim-rbk",
        generation_id=compact_id,
        input_fingerprint=fingerprint,
        manifest_checksum=checksum,
    )
    db_session.flush()
    assert (
        db_session.scalar(
            select(func.count()).select_from(JobEvent).where(JobEvent.job_id == job_id)
        )
        == 1
    )

    db_session.rollback()
    db_session.expire_all()
    active = db_session.get(SettlementProjectionActive, "settlement")
    compact = db_session.get(SettlementProjectionGeneration, compact_id)
    assert active is not None and active.generation_id == head
    assert compact is not None
    assert compact.state == "ready"
    assert compact.published_at is None
    assert db_session.scalar(select(func.count()).select_from(JobEvent)) == 0
    # The seeded frozen row was part of the same caller transaction.
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(SettlementStatement)
            .where(SettlementStatement.statement_id == statement_id)
        )
        == 0
    )


def test_publish_fails_closed_when_compact_manifest_missing(
    db_session: Session,
) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-miss")
    statement_id, _, _ = _seed_statement(db_session, "cmp-miss")
    before = _frozen_snapshot(db_session, statement_id)
    job_id = _seed_compaction_job(db_session)

    victim = db_session.scalar(
        select(SettlementProjectionPartitionManifest)
        .where(SettlementProjectionPartitionManifest.generation_id == compact_id)
        .limit(1)
    )
    assert victim is not None
    db_session.delete(victim)
    db_session.flush()

    with pytest.raises(RuntimeError, match="verification failed"):
        publish_settlement_compaction(
            db_session,
            job_id=job_id,
            claim_id="claim-1",
            generation_id=compact_id,
            input_fingerprint=fingerprint,
            manifest_checksum=checksum,
        )

    _assert_refused(
        db_session,
        head=head,
        compact_id=compact_id,
        statement_id=statement_id,
        snapshot=before,
    )


def test_publish_fails_closed_when_compact_manifest_checksum_tampered(
    db_session: Session,
) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-row")
    statement_id, _, _ = _seed_statement(db_session, "cmp-row")
    before = _frozen_snapshot(db_session, statement_id)
    job_id = _seed_compaction_job(db_session)

    row = db_session.scalar(
        select(SettlementProjectionPartitionManifest)
        .where(
            SettlementProjectionPartitionManifest.generation_id == compact_id,
            SettlementProjectionPartitionManifest.owner_state == "owned",
        )
        .limit(1)
    )
    assert row is not None
    row.checksum = "f" * 64
    db_session.flush()

    with pytest.raises(RuntimeError, match="verification failed"):
        publish_settlement_compaction(
            db_session,
            job_id=job_id,
            claim_id="claim-1",
            generation_id=compact_id,
            input_fingerprint=fingerprint,
            manifest_checksum=checksum,
        )

    _assert_refused(
        db_session,
        head=head,
        compact_id=compact_id,
        statement_id=statement_id,
        snapshot=before,
    )


def test_publish_fails_closed_when_closure_source_digest_tampered(
    db_session: Session,
) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-clos")
    statement_id, _, _ = _seed_statement(db_session, "cmp-clos")
    before = _frozen_snapshot(db_session, statement_id)
    job_id = _seed_compaction_job(db_session)

    closure = db_session.scalar(
        select(SettlementProjectionCompactionClosure)
        .where(
            SettlementProjectionCompactionClosure.compact_generation_id == compact_id
        )
        .limit(1)
    )
    assert closure is not None
    closure.source_digest = "0" * 64
    db_session.flush()

    with pytest.raises(RuntimeError, match="verification failed"):
        publish_settlement_compaction(
            db_session,
            job_id=job_id,
            claim_id="claim-1",
            generation_id=compact_id,
            input_fingerprint=fingerprint,
            manifest_checksum=checksum,
        )

    _assert_refused(
        db_session,
        head=head,
        compact_id=compact_id,
        statement_id=statement_id,
        snapshot=before,
    )


def test_publish_fails_closed_when_closure_row_missing(
    db_session: Session,
) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-gone")
    statement_id, _, _ = _seed_statement(db_session, "cmp-gone")
    before = _frozen_snapshot(db_session, statement_id)
    job_id = _seed_compaction_job(db_session)

    missing = db_session.scalar(
        select(SettlementProjectionCompactionClosure)
        .where(
            SettlementProjectionCompactionClosure.compact_generation_id == compact_id
        )
        .limit(1)
    )
    assert missing is not None
    db_session.delete(missing)
    db_session.flush()

    with pytest.raises(RuntimeError, match="verification failed"):
        publish_settlement_compaction(
            db_session,
            job_id=job_id,
            claim_id="claim-1",
            generation_id=compact_id,
            input_fingerprint=fingerprint,
            manifest_checksum=checksum,
        )

    _assert_refused(
        db_session,
        head=head,
        compact_id=compact_id,
        statement_id=statement_id,
        snapshot=before,
    )


def test_publish_fails_closed_when_checkpoint_counts_tampered(
    db_session: Session,
) -> None:
    from apps.worker.projection_publish import publish_settlement_compaction

    head, compact_id, fingerprint, checksum = _ready_compact_head(db_session, "cmp-cnt")
    statement_id, _, _ = _seed_statement(db_session, "cmp-cnt")
    before = _frozen_snapshot(db_session, statement_id)
    job_id = _seed_compaction_job(db_session)

    db_session.expire_all()
    compact = db_session.get(SettlementProjectionGeneration, compact_id)
    assert compact is not None and isinstance(compact.checkpoint_json, dict)
    tampered = dict(compact.checkpoint_json)
    tampered["partition_count"] = int(tampered["partition_count"]) + 1
    compact.checkpoint_json = tampered
    db_session.flush()

    with pytest.raises(RuntimeError, match="verification failed"):
        publish_settlement_compaction(
            db_session,
            job_id=job_id,
            claim_id="claim-1",
            generation_id=compact_id,
            input_fingerprint=fingerprint,
            manifest_checksum=checksum,
        )

    _assert_refused(
        db_session,
        head=head,
        compact_id=compact_id,
        statement_id=statement_id,
        snapshot=before,
    )
