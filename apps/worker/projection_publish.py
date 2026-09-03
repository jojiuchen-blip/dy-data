"""Generic projection publication mutation for the final stage transaction."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    JobEvent,
    JobRun,
    JobStageRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
)
from apps.worker.stage_runner import BeforeSuccessCommit


_LOWER_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_ONCE_PREFIX = "finalize-consume-v1:"
_REBUILD_ONCE_PREFIX = "settlement-rebuild-publish-v1:"


def _identity(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{label} must be a non-empty canonical string")
    return value


def _digest(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _LOWER_HEX_64.fullmatch(value) is None:
        raise ValueError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def projection_publish_once_key(parent_job_id: str, input_fingerprint: str) -> str:
    if not isinstance(parent_job_id, str):
        raise TypeError("parent_job_id must be a string")
    fingerprint = _digest(input_fingerprint, label="input_fingerprint")
    suffix = hashlib.sha256(
        f"{parent_job_id}|{fingerprint}".encode("utf-8")
    ).hexdigest()
    key = f"{_ONCE_PREFIX}{suffix}"
    if len(key) != 84:  # pragma: no cover - fixed protocol assertion
        raise RuntimeError("projection publication once key has invalid length")
    return key


def settlement_rebuild_publish_once_key(job_id: str, input_fingerprint: str) -> str:
    """Return the durable once key for an admin settlement rebuild publish."""

    if not isinstance(job_id, str):
        raise TypeError("job_id must be a string")
    fingerprint = _digest(input_fingerprint, label="input_fingerprint")
    suffix = hashlib.sha256(
        f"{job_id}|{fingerprint}".encode("utf-8")
    ).hexdigest()
    key = f"{_REBUILD_ONCE_PREFIX}{suffix}"
    if len(key) > 128:  # pragma: no cover - fixed protocol assertion
        raise RuntimeError("settlement rebuild publication once key is too long")
    return key


@dataclass(frozen=True)
class _ProjectionPublishMutation(BeforeSuccessCommit):
    generation_id: str
    base_generation_id: str
    input_fingerprint: str
    manifest_checksum: str
    parent_job_id: str

    def apply(
        self, session: Session, *, job: JobRun, stage: JobStageRun
    ) -> None:
        if not session.in_transaction():
            raise RuntimeError("projection publication requires the runner transaction")
        if (
            job.job_id != stage.job_id
            or job.job_kind != "finalize"
            or stage.stage_name != "finalize"
            or job.parent_job_id != self.parent_job_id
        ):
            raise RuntimeError("projection publication event owner is invalid")

        active_statement = select(SettlementProjectionActive).where(
            SettlementProjectionActive.projection_name == "settlement"
        )
        generation_statement = select(SettlementProjectionGeneration).where(
            SettlementProjectionGeneration.generation_id == self.generation_id
        )
        if session.get_bind().dialect.name == "postgresql":
            active_statement = active_statement.with_for_update()
            generation_statement = generation_statement.with_for_update()
        active = session.scalar(active_statement)
        generation = session.scalar(generation_statement)
        if active is None:
            raise RuntimeError("settlement active pointer is missing")
        if generation is None:
            raise RuntimeError("settlement projection generation is missing")
        if (
            generation.projection_name != "settlement"
            or generation.generation_kind not in {"lineage", "compact"}
            or generation.base_generation_id != self.base_generation_id
            or generation.input_fingerprint != self.input_fingerprint
        ):
            raise RuntimeError("settlement projection generation metadata conflicts")
        if generation.manifest_checksum != self.manifest_checksum:
            raise RuntimeError("settlement projection manifest checksum conflicts")

        already_published = (
            active.generation_id == self.generation_id
            and generation.state == "published"
        )
        if not already_published:
            if active.generation_id != self.base_generation_id:
                raise RuntimeError("settlement active pointer changed before publication")
            if generation.state != "ready" or generation.published_at is not None:
                raise RuntimeError("settlement projection generation is not ready")
            generation.state = "published"
            generation.published_at = datetime.now(UTC)
            active.generation_id = self.generation_id

        once_key = projection_publish_once_key(
            self.parent_job_id, self.input_fingerprint
        )
        payload = {
            "input_fingerprint": self.input_fingerprint,
            "generation_id": self.generation_id,
            "manifest_checksum": self.manifest_checksum,
            "base_generation_id": self.base_generation_id,
        }
        existing_event = session.scalar(
            select(JobEvent).where(
                JobEvent.job_id == job.job_id,
                JobEvent.idempotency_key == once_key,
            )
        )
        if existing_event is not None:
            if (
                existing_event.stage_run_id != stage.stage_run_id
                or existing_event.event_type != "settlement_projection_published"
                or existing_event.payload_json != payload
            ):
                raise RuntimeError("projection publication once event conflicts")
            return
        event_suffix = hashlib.sha256(
            f"{job.job_id}|{once_key}".encode("utf-8")
        ).hexdigest()
        session.add(
            JobEvent(
                event_id=f"event-projection-{event_suffix}",
                job_id=job.job_id,
                stage_run_id=stage.stage_run_id,
                attempt_id=None,
                event_type="settlement_projection_published",
                from_status="running",
                to_status="running",
                actor_type="worker" if job.lease_owner else "system",
                actor_id=job.lease_owner,
                reason="settlement projection published",
                idempotency_key=once_key,
                payload_json=payload,
                occurred_at=datetime.now(UTC),
            )
        )


def make_projection_publish_mutation(
    *,
    generation_id: str,
    base_generation_id: str,
    input_fingerprint: str,
    manifest_checksum: str,
    parent_job_id: str,
) -> BeforeSuccessCommit:
    return _ProjectionPublishMutation(
        generation_id=_identity(generation_id, label="generation_id"),
        base_generation_id=_identity(
            base_generation_id, label="base_generation_id"
        ),
        input_fingerprint=_digest(
            input_fingerprint, label="input_fingerprint"
        ),
        manifest_checksum=_digest(
            manifest_checksum, label="manifest_checksum"
        ),
        parent_job_id=_identity(parent_job_id, label="parent_job_id"),
    )


def publish_settlement_rebuild(
    session: Session,
    *,
    job_id: str,
    generation_id: str,
    base_generation_id: str,
    input_fingerprint: str,
    manifest_checksum: str,
) -> dict[str, str]:
    """Publish an admin rebuild generation with an active-pointer CAS.

    Admin rule changes use the legacy settlement rebuild job rather than the
    daily finalize state machine.  They still need the same durable pointer
    promotion and once-only audit event, otherwise readers pinned to lineage
    continue serving the previous overlay generation.
    """

    job_id = _identity(job_id, label="job_id")
    generation_id = _identity(generation_id, label="generation_id")
    base_generation_id = _identity(base_generation_id, label="base_generation_id")
    input_fingerprint = _digest(input_fingerprint, label="input_fingerprint")
    manifest_checksum = _digest(manifest_checksum, label="manifest_checksum")

    job = session.get(JobRun, job_id)
    if not session.in_transaction():  # pragma: no cover - get() auto-begins
        raise RuntimeError("settlement rebuild publication requires a transaction")
    if job is None or job.job_name != "settlement_rebuild":
        raise RuntimeError("settlement rebuild publication job is invalid")

    active_statement = select(SettlementProjectionActive).where(
        SettlementProjectionActive.projection_name == "settlement"
    )
    generation_statement = select(SettlementProjectionGeneration).where(
        SettlementProjectionGeneration.generation_id == generation_id
    )
    if session.get_bind().dialect.name == "postgresql":
        active_statement = active_statement.with_for_update()
        generation_statement = generation_statement.with_for_update()
    active = session.scalar(active_statement)
    generation = session.scalar(generation_statement)
    if active is None:
        raise RuntimeError("settlement active pointer is missing")
    if generation is None:
        raise RuntimeError("settlement rebuild generation is missing")
    if (
        generation.projection_name != "settlement"
        or generation.generation_kind != "lineage"
        or generation.base_generation_id != base_generation_id
        or generation.input_fingerprint != input_fingerprint
        or (
            generation.source_job_id is not None
            and generation.source_job_id != job_id
        )
    ):
        raise RuntimeError("settlement rebuild generation metadata conflicts")
    if generation.manifest_checksum != manifest_checksum:
        raise RuntimeError("settlement rebuild manifest checksum conflicts")

    already_published = (
        active.generation_id == generation_id and generation.state == "published"
    )
    if not already_published:
        if active.generation_id != base_generation_id:
            raise RuntimeError("settlement active pointer changed before rebuild publish")
        if generation.state != "ready" or generation.published_at is not None:
            raise RuntimeError("settlement rebuild generation is not ready")
        generation.state = "published"
        generation.published_at = datetime.now(UTC)
        active.generation_id = generation_id

    once_key = settlement_rebuild_publish_once_key(job_id, input_fingerprint)
    payload = {
        "input_fingerprint": input_fingerprint,
        "generation_id": generation_id,
        "manifest_checksum": manifest_checksum,
        "base_generation_id": base_generation_id,
    }
    existing_event = session.scalar(
        select(JobEvent).where(
            JobEvent.job_id == job_id,
            JobEvent.idempotency_key == once_key,
        )
    )
    if existing_event is not None:
        if (
            existing_event.stage_run_id is not None
            or existing_event.event_type != "settlement_projection_published"
            or existing_event.payload_json != payload
        ):
            raise RuntimeError("settlement rebuild publication once event conflicts")
        return payload

    event_suffix = hashlib.sha256(
        f"{job_id}|{once_key}".encode("utf-8")
    ).hexdigest()
    session.add(
        JobEvent(
            event_id=f"event-settlement-rebuild-projection-{event_suffix}",
            job_id=job_id,
            stage_run_id=None,
            attempt_id=None,
            event_type="settlement_projection_published",
            from_status=job.status,
            to_status=job.status,
            actor_type="worker" if job.lease_owner else "system",
            actor_id=job.lease_owner,
            reason="settlement rebuild projection published",
            idempotency_key=once_key,
            payload_json=payload,
            occurred_at=datetime.now(UTC),
        )
    )
    return payload


__all__ = [
    "make_projection_publish_mutation",
    "publish_settlement_rebuild",
    "projection_publish_once_key",
    "settlement_rebuild_publish_once_key",
]
