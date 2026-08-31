"""Fenced sparse-projection finalize orchestration."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationRuleVersion,
    JobEvent,
    JobRun,
    JobStageRun,
)
from apps.worker.stage_runner import StageHandlerOutput, is_daily_execution_lease_live


_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_RULES = 64


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, datetime):
        current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return current.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise RuntimeError(f"finalize input contains unsupported value: {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _identity(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise RuntimeError(f"{label} must be a canonical non-empty string")
    return value


def _strict_count(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"{label} must be a non-negative integer")
    return value


def _string_set(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RuntimeError(f"{label} must be a list")
    return tuple(sorted({_identity(item, label=label) for item in value}))


@dataclass(frozen=True)
class StageFence:
    job_id: str
    stage_run_id: str
    lease_epoch: int
    committed_at: datetime
    status: str

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "StageFence":
        try:
            committed_at = datetime.fromisoformat(str(payload["committed_at"]))
            lease_epoch = int(payload["lease_epoch"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("finalize settle stage fence is malformed") from exc
        if committed_at.tzinfo is None:
            committed_at = committed_at.replace(tzinfo=UTC)
        status = str(payload.get("status") or "")
        if lease_epoch < 0 or status != "success":
            raise RuntimeError("finalize settle stage fence is malformed")
        return cls(
            job_id=_identity(payload.get("job_id"), label="fence job_id"),
            stage_run_id=_identity(
                payload.get("stage_run_id"), label="fence stage_run_id"
            ),
            lease_epoch=lease_epoch,
            committed_at=committed_at.astimezone(UTC),
            status=status,
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "stage_run_id": self.stage_run_id,
            "lease_epoch": self.lease_epoch,
            "committed_at": self.committed_at.astimezone(UTC).isoformat(),
            "status": self.status,
        }


@dataclass(frozen=True)
class FenceToken:
    finalize_job_id: str
    lease_owner: str
    lease_epoch: int
    attempt_id: str
    component_instance_id: str
    settle_stages: tuple[StageFence, ...]

    @classmethod
    def from_job(cls, job: JobRun | None, lease_token: Any) -> "FenceToken":
        if job is None or job.job_id != getattr(lease_token, "job_id", None):
            raise RuntimeError("finalize lease job does not match metadata")
        metadata = job.metadata_json or {}
        raw_fences = metadata.get("settle_stage_fences")
        if not isinstance(raw_fences, list) or not raw_fences:
            raise RuntimeError("finalize settle stage fences are missing")
        fences = tuple(StageFence.from_json(item) for item in raw_fences)
        if tuple(fence.job_id for fence in fences) != tuple(
            sorted(fence.job_id for fence in fences)
        ):
            raise RuntimeError("finalize settle stage fences are not ordered")
        return cls(
            finalize_job_id=job.job_id,
            lease_owner=_identity(
                getattr(lease_token, "lease_owner", None), label="lease_owner"
            ),
            lease_epoch=int(getattr(lease_token, "lease_epoch", -1)),
            attempt_id=_identity(
                getattr(lease_token, "attempt_id", None), label="attempt_id"
            ),
            component_instance_id=_identity(
                getattr(lease_token, "component_instance_id", None),
                label="component_instance_id",
            ),
            settle_stages=fences,
        )


@dataclass(frozen=True)
class FinalizeInput:
    parent_job_id: str
    finalize_job_id: str
    base_generation_id: str
    generation_id: str
    input_fingerprint: str
    affected_months: tuple[str, ...]
    affected_store_ids: tuple[str, ...]
    snapshot_date: date
    published_rule_ids: tuple[str, ...]
    closure_policy_hash: str
    settle_stage_fences: tuple[StageFence, ...]
    checkpoint_payload: Mapping[str, Any]


def _assert_live_fence(session: Session, fence_token: FenceToken, *, lock: bool) -> None:
    if not is_daily_execution_lease_live(
        session,
        job_id=fence_token.finalize_job_id,
        lease_owner=fence_token.lease_owner,
        lease_epoch=fence_token.lease_epoch,
        attempt_id=fence_token.attempt_id,
        component_instance_id=fence_token.component_instance_id,
        lock=lock,
    ):
        raise RuntimeError("finalize execution fence is no longer valid")


def _stage_fence(stage: JobStageRun) -> StageFence:
    if stage.committed_at is None:
        raise RuntimeError("finalize settle stage is not committed")
    committed_at = stage.committed_at
    if committed_at.tzinfo is None:
        committed_at = committed_at.replace(tzinfo=UTC)
    return StageFence(
        job_id=stage.job_id,
        stage_run_id=stage.stage_run_id,
        lease_epoch=int(stage.lease_epoch or 0),
        committed_at=committed_at.astimezone(UTC),
        status=stage.status,
    )


def validate_finalize_input(
    session: Session,
    parent_job_id: str,
    fence_token: FenceToken,
) -> FinalizeInput:
    """Validate and fingerprint only durable T3.3 stage outputs."""

    from apps.api.dy_api.models import (
        SettlementProjectionActive,
        SettlementProjectionGeneration,
    )
    from apps.worker.daily_windows import (
        _required_parent_stage_for_finalize,
        _validated_daily_children_for_parent,
    )

    parent_statement = select(JobRun).where(
        JobRun.job_id == parent_job_id,
        JobRun.job_kind == "range_sync",
    )
    if session.get_bind().dialect.name == "postgresql":
        parent_statement = parent_statement.with_for_update()
    parent = session.scalar(parent_statement)
    if parent is None:
        raise RuntimeError("finalize range parent is missing")
    metadata = parent.metadata_json or {}
    if (
        metadata.get("target") not in {"all", "settlement"}
        or metadata.get("timezone") != "Asia/Shanghai"
        or parent.status in {"success", "failed", "cancelled"}
        or parent.window_start is None
        or parent.window_end is None
        or parent.window_end <= parent.window_start
    ):
        raise RuntimeError("finalize range parent identity is invalid")
    finalize_job = session.get(JobRun, fence_token.finalize_job_id)
    if (
        finalize_job is None
        or finalize_job.parent_job_id != parent_job_id
        or finalize_job.job_kind != "finalize"
        or (finalize_job.metadata_json or {}).get("required_stages") != ["finalize"]
        or (finalize_job.metadata_json or {}).get("target") != metadata.get("target")
    ):
        raise RuntimeError("finalize job identity is invalid")
    _assert_live_fence(session, fence_token, lock=True)

    children = _validated_daily_children_for_parent(session, parent)
    if not children or any(child.status != "success" for child in children):
        raise RuntimeError("finalize daily children are incomplete")
    required_parent = _required_parent_stage_for_finalize(session, parent)
    if required_parent is not None and (
        required_parent.status != "success" or required_parent.committed_at is None
    ):
        raise RuntimeError("finalize required parent stage is incomplete")

    observed_fences: list[StageFence] = []
    child_payloads: list[dict[str, Any]] = []
    affected_months: set[str] = set()
    affected_store_ids: set[str] = set()
    rule_hints: list[Any] = []
    # The durable fence envelope is canonicalized by hashed job id, not by
    # business date.  Keep validation and fingerprint construction in that same
    # order so a planner contract-version bump cannot create an order mismatch.
    for child in sorted(children, key=lambda item: item.job_id):
        required_stages = (child.metadata_json or {}).get("required_stages")
        if not isinstance(required_stages, list) or "settle" not in required_stages:
            raise RuntimeError("finalize child required stages are invalid")
        stages = list(
            session.scalars(
                select(JobStageRun)
                .where(
                    JobStageRun.job_id == child.job_id,
                    JobStageRun.stage_name.in_(tuple(required_stages)),
                )
                .order_by(JobStageRun.stage_name)
            )
        )
        by_name = {stage.stage_name: stage for stage in stages}
        if set(by_name) != set(required_stages) or any(
            stage.status != "success" or stage.committed_at is None
            for stage in stages
        ):
            raise RuntimeError("finalize child stage set is incomplete")
        settle = by_name["settle"]
        observed_fences.append(_stage_fence(settle))
        checkpoint = settle.checkpoint_json
        if not isinstance(checkpoint, dict):
            raise RuntimeError("finalize settle checkpoint is malformed")
        summary = checkpoint.get("settlement_summary")
        score = checkpoint.get("store_score_snapshot")
        if not isinstance(summary, dict) or not isinstance(score, dict):
            raise RuntimeError("finalize settle output is incomplete")
        if summary.get("completed") is not True:
            raise RuntimeError("finalize settlement summary is incomplete")
        for key in (
            "impact_count",
            "coupon_count",
            "detail_count",
            "result_count",
            "adjustment_count",
        ):
            _strict_count(summary.get(key, 0), label=f"settlement_summary.{key}")
        months = _string_set(
            summary.get("affected_months"), label="affected_months"
        )
        stores = _string_set(
            summary.get("affected_store_ids"), label="affected_store_ids"
        )
        score_stores = _string_set(
            score.get("affected_store_ids"), label="score affected_store_ids"
        )
        if score.get("deferred") is not True or score.get("consumer") != "T3.4.finalize":
            raise RuntimeError("finalize score handoff is invalid")
        if stores != score_stores:
            raise RuntimeError("finalize score store closure conflicts with settlement")
        _canonical_json(score.get("rule_closure"))
        affected_months.update(months)
        affected_store_ids.update(stores)
        rule_hints.append(score.get("rule_closure"))
        child_payloads.append(
            {
                "job_id": child.job_id,
                "business_date": child.business_date,
                "settlement_summary": summary,
                "store_score_snapshot": score,
                "fence": observed_fences[-1].as_json(),
            }
        )

    observed = tuple(observed_fences)
    if observed != fence_token.settle_stages:
        raise RuntimeError("finalize settle stage fence changed")
    active = session.get(SettlementProjectionActive, "settlement")
    if active is None or active.generation_id is None:
        raise RuntimeError("finalize active settlement base is missing")
    base = session.get(SettlementProjectionGeneration, active.generation_id)
    if base is None or base.state != "published" or base.projection_name != "settlement":
        raise RuntimeError("finalize active settlement base is invalid")

    published_rule_ids: tuple[str, ...] = ()
    if affected_store_ids:
        published_rule_ids = tuple(
            session.scalars(
                select(ClueAllocationRuleVersion.rule_version_id)
                .where(ClueAllocationRuleVersion.status == "published")
                .order_by(ClueAllocationRuleVersion.rule_version_id)
                .limit(_MAX_RULES + 1)
            )
        )
        if not published_rule_ids or len(published_rule_ids) > _MAX_RULES:
            raise RuntimeError("finalize published rule closure is unavailable")
    checkpoint_payload = _canonical_value(
        {
            "protocol": "settlement-finalize-v1",
            "parent_job_id": parent_job_id,
            "target": metadata.get("target"),
            "window_start": parent.window_start,
            "window_end": parent.window_end,
            "children": child_payloads,
        }
    )
    input_fingerprint = _digest(checkpoint_payload)
    closure_policy_hash = _digest(
        {"published_rule_ids": published_rule_ids, "hints": rule_hints}
    )
    snapshot_date = max(child.business_date for child in children if child.business_date)
    return FinalizeInput(
        parent_job_id=parent_job_id,
        finalize_job_id=finalize_job.job_id,
        base_generation_id=base.generation_id,
        generation_id=f"settlement-lineage:{input_fingerprint}",
        input_fingerprint=input_fingerprint,
        affected_months=tuple(sorted(affected_months)),
        affected_store_ids=tuple(sorted(affected_store_ids)),
        snapshot_date=snapshot_date,
        published_rule_ids=published_rule_ids,
        closure_policy_hash=closure_policy_hash,
        settle_stage_fences=observed,
        checkpoint_payload=checkpoint_payload,
    )


def _validate_same_input(
    session_factory: Callable[[], Session],
    expected: FinalizeInput,
    fence_token: FenceToken,
) -> None:
    with session_factory() as session:
        current = validate_finalize_input(session, expected.parent_job_id, fence_token)
        if (
            current.input_fingerprint != expected.input_fingerprint
            or current.base_generation_id != expected.base_generation_id
            or current.generation_id != expected.generation_id
        ):
            raise RuntimeError("finalize input changed during staging")


def _fenced_session_factory(
    session_factory: Callable[[], Session],
    fence_token: FenceToken,
) -> Callable[[], Session]:
    """Fence every builder-owned short transaction without changing builders."""

    def factory() -> Session:
        session = session_factory()

        def before_commit(current: Session) -> None:
            _assert_live_fence(current, fence_token, lock=False)

        event.listen(session, "before_commit", before_commit)
        return session

    return factory


def _ensure_staging_generation(
    session_factory: Callable[[], Session],
    value: FinalizeInput,
) -> None:
    from apps.api.dy_api.models import (
        SettlementProjectionActive,
        SettlementProjectionGeneration,
    )

    with session_factory() as session:
        active = session.get(SettlementProjectionActive, "settlement")
        base = session.get(SettlementProjectionGeneration, value.base_generation_id)
        if active is None or active.generation_id != value.base_generation_id:
            raise RuntimeError("finalize active pointer changed before staging")
        if base is None or base.state != "published":
            raise RuntimeError("finalize base generation is not published")
        generation = session.get(SettlementProjectionGeneration, value.generation_id)
        if generation is None:
            generation = SettlementProjectionGeneration(
                generation_id=value.generation_id,
                base_generation_id=value.base_generation_id,
                generation_kind="lineage",
                compaction_base_generation_id=None,
                projection_name="settlement",
                state="staging",
                input_fingerprint=value.input_fingerprint,
                lineage_depth=int(base.lineage_depth) + 1,
                estimated_write_rows=0,
                estimated_write_bytes=0,
                estimated_wal_bytes=0,
                estimated_disk_headroom_bytes=0,
                checkpoint_json={
                    "phase": "finalize_staging",
                    "expected_active_pointer": value.base_generation_id,
                },
                last_key=None,
                manifest_checksum=None,
                source_job_id=value.finalize_job_id,
                source_input_json={"finalize": dict(value.checkpoint_payload)},
            )
            session.add(generation)
        elif (
            generation.base_generation_id != value.base_generation_id
            or generation.input_fingerprint != value.input_fingerprint
            or generation.state not in {"staging", "ready", "published"}
        ):
            raise RuntimeError("finalize deterministic generation conflicts")
        session.commit()
def _ready_generation(
    session_factory: Callable[[], Session],
    value: FinalizeInput,
) -> tuple[str, int, int]:
    from apps.api.dy_api.models import (
        SettlementProjectionActive,
        SettlementProjectionGeneration,
        SettlementProjectionPartitionManifest,
    )
    from apps.worker.legacy_projection_bootstrap import _manifest_checksum

    with session_factory() as session:
        generation = session.scalar(
            select(SettlementProjectionGeneration)
            .where(SettlementProjectionGeneration.generation_id == value.generation_id)
            .with_for_update()
        )
        if generation is None or generation.state not in {"staging", "ready"}:
            raise RuntimeError("finalize generation is not writable")
        active = session.get(SettlementProjectionActive, "settlement")
        if active is None or active.generation_id != value.base_generation_id:
            raise RuntimeError("finalize active pointer changed before ready")
        manifests = list(
            session.scalars(
                select(SettlementProjectionPartitionManifest)
                .where(
                    SettlementProjectionPartitionManifest.generation_id
                    == value.generation_id
                )
                .order_by(
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                )
            )
        )
        manifest_payload = [
            {
                "artifact": row.artifact,
                "partition_key": row.partition_key,
                "owner_state": row.owner_state,
                "source_kind": row.source_kind,
                "data_generation_id": row.data_generation_id,
                "base_generation_id": row.base_generation_id,
                "row_count": int(row.row_count),
                "amount_total_cent": int(row.amount_total_cent),
                "status_counts_json": dict(row.status_counts_json or {}),
                "checksum": row.checksum,
            }
            for row in manifests
        ]
        manifest_checksum = _manifest_checksum(manifest_payload)
        row_count = sum(int(row.row_count) for row in manifests)
        manifest_count = len(manifests)
        write_rows = 1 + manifest_count + row_count
        write_bytes = 16_384 + 4_096 * (manifest_count + row_count)
        generation.state = "ready"
        generation.manifest_checksum = manifest_checksum
        generation.last_key = manifests[-1].last_key if manifests else None
        generation.estimated_write_rows = write_rows
        generation.estimated_write_bytes = write_bytes
        generation.estimated_wal_bytes = 2 * write_bytes
        generation.estimated_disk_headroom_bytes = 0
        generation.checkpoint_json = {
            "phase": "ready",
            "parent_job_id": value.parent_job_id,
            "input_fingerprint": value.input_fingerprint,
            "expected_active_pointer": value.base_generation_id,
            "manifest_count": manifest_count,
            "row_count": row_count,
            "last_key": generation.last_key,
        }
        source_input = dict(generation.source_input_json or {})
        source_input["finalize"] = dict(value.checkpoint_payload)
        generation.source_input_json = source_input
        session.commit()
        return manifest_checksum, manifest_count, row_count


def run_finalize_stage(
    session_factory: Callable[[], Session],
    *,
    parent_job_id: str,
    fence_token: FenceToken,
    batch_size: int = 200,
    settlement_builder: Callable[..., Any] | None = None,
    score_builder: Callable[..., Any] | None = None,
    publish_mutation_factory: Callable[..., Any] | None = None,
) -> StageHandlerOutput:
    """Build, verify, and return the publication mutation for one finalize job."""

    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 400:
        raise ValueError("batch_size must be an integer between 1 and 400")
    with session_factory() as session:
        value = validate_finalize_input(session, parent_job_id, fence_token)
    operation_factory = _fenced_session_factory(session_factory, fence_token)
    _ensure_staging_generation(operation_factory, value)
    _validate_same_input(session_factory, value, fence_token)

    if value.affected_months:
        if settlement_builder is None:
            from apps.worker.settlement import build_settlement_sparse_overlay

            settlement_builder = build_settlement_sparse_overlay
        settlement_builder(
            operation_factory,
            generation_id=value.generation_id,
            base_generation_id=value.base_generation_id,
            affected_months=value.affected_months,
            batch_size=batch_size,
            input_fingerprint=value.input_fingerprint,
        )
        _validate_same_input(session_factory, value, fence_token)
    if value.affected_store_ids:
        if score_builder is None:
            from apps.worker.clue_allocation import build_score_sparse_overlay

            score_builder = build_score_sparse_overlay
        score_builder(
            operation_factory,
            generation_id=value.generation_id,
            base_generation_id=value.base_generation_id,
            affected_store_ids=value.affected_store_ids,
            published_rule_ids=value.published_rule_ids,
            snapshot_date=value.snapshot_date,
            batch_size=batch_size,
            closure_policy_hash=value.closure_policy_hash,
        )
        _validate_same_input(session_factory, value, fence_token)
    manifest_checksum, manifest_count, row_count = _ready_generation(
        operation_factory, value
    )
    _validate_same_input(session_factory, value, fence_token)
    if publish_mutation_factory is None:
        from apps.worker.projection_publish import make_projection_publish_mutation

        publish_mutation_factory = make_projection_publish_mutation
    mutation = publish_mutation_factory(
        generation_id=value.generation_id,
        base_generation_id=value.base_generation_id,
        input_fingerprint=value.input_fingerprint,
        manifest_checksum=manifest_checksum,
        parent_job_id=value.parent_job_id,
    )
    return StageHandlerOutput(
        checkpoint={
            "protocol": "settlement-finalize-v1",
            "parent_job_id": value.parent_job_id,
            "base_generation_id": value.base_generation_id,
            "generation_id": value.generation_id,
            "input_fingerprint": value.input_fingerprint,
            "manifest_checksum": manifest_checksum,
            "manifest_count": manifest_count,
            "row_count": row_count,
            "affected_months": list(value.affected_months),
            "affected_store_ids": list(value.affected_store_ids),
        },
        before_success_commit=mutation,
    )


run_finalize_stage.requires_independent_sessions = True


def verify_finalize_publication(
    session: Session,
    finalize_job_id: str,
    *,
    require_active: bool = True,
) -> Mapping[str, Any]:
    from apps.api.dy_api.models import (
        SettlementProjectionActive,
        SettlementProjectionGeneration,
    )
    from apps.worker.projection_publish import projection_publish_once_key

    job = session.get(JobRun, finalize_job_id)
    if job is None or job.job_kind != "finalize" or not job.parent_job_id:
        raise RuntimeError("finalize publication job is invalid")
    stage = session.scalar(
        select(JobStageRun).where(
            JobStageRun.job_id == finalize_job_id,
            JobStageRun.stage_name == "finalize",
        )
    )
    if stage is None or stage.status != "success" or stage.committed_at is None:
        raise RuntimeError("finalize publication stage is incomplete")
    checkpoint = stage.checkpoint_json
    if not isinstance(checkpoint, dict):
        raise RuntimeError("finalize publication checkpoint is invalid")
    generation_id = _identity(checkpoint.get("generation_id"), label="generation_id")
    base_generation_id = _identity(
        checkpoint.get("base_generation_id"), label="base_generation_id"
    )
    input_fingerprint = _identity(
        checkpoint.get("input_fingerprint"), label="input_fingerprint"
    )
    manifest_checksum = _identity(
        checkpoint.get("manifest_checksum"), label="manifest_checksum"
    )
    if _HEX_64.fullmatch(input_fingerprint) is None or _HEX_64.fullmatch(manifest_checksum) is None:
        raise RuntimeError("finalize publication digest is invalid")
    generation = session.get(SettlementProjectionGeneration, generation_id)
    active = session.get(SettlementProjectionActive, "settlement")
    if (
        generation is None
        or generation.state != "published"
        or generation.base_generation_id != base_generation_id
        or generation.input_fingerprint != input_fingerprint
        or generation.manifest_checksum != manifest_checksum
        or active is None
        or (require_active and active.generation_id != generation_id)
    ):
        raise RuntimeError("finalize durable publication is inconsistent")
    once_key = projection_publish_once_key(job.parent_job_id, input_fingerprint)
    event = session.scalar(
        select(JobEvent).where(
            JobEvent.job_id == finalize_job_id,
            JobEvent.idempotency_key == once_key,
        )
    )
    expected_payload = {
        "input_fingerprint": input_fingerprint,
        "generation_id": generation_id,
        "manifest_checksum": manifest_checksum,
        "base_generation_id": base_generation_id,
    }
    if (
        event is None
        or event.stage_run_id != stage.stage_run_id
        or event.event_type != "settlement_projection_published"
        or event.payload_json != expected_payload
    ):
        raise RuntimeError("finalize publication event is inconsistent")
    return expected_payload


def promote_range_parent_if_ready(session: Session, parent_job_id: str) -> bool:
    """Idempotently promote a range parent after durable finalize completion."""

    from apps.api.dy_api.models import SettlementProjectionActive
    from apps.worker.daily_windows import (
        _required_parent_stage_for_finalize,
        _validated_daily_children_for_parent,
    )

    with session.begin_nested():
        statement = select(JobRun).where(
            JobRun.job_id == parent_job_id,
            JobRun.job_kind == "range_sync",
        )
        if session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        parent = session.scalar(statement)
        if parent is None:
            raise RuntimeError("finalize range parent is missing")
        target = (parent.metadata_json or {}).get("target")
        if target not in {"all", "settlement"}:
            return False
        finalize_rows = list(
            session.scalars(
                select(JobRun).where(
                    JobRun.parent_job_id == parent_job_id,
                    JobRun.job_kind == "finalize",
                )
            )
        )
        if len(finalize_rows) != 1 or finalize_rows[0].status != "success":
            return False
        finalize_job = finalize_rows[0]
        if parent.status == "success":
            # A completed range remains durable after a later range publishes
            # a successor and advances the active pointer.  Reconciliation is
            # for incomplete parents only; re-check the immutable generation
            # and once-event without requiring this historical root to remain
            # active forever.
            publication = verify_finalize_publication(
                session,
                finalize_job.job_id,
                require_active=False,
            )
            active = session.get(SettlementProjectionActive, "settlement")
            if active is None:
                raise RuntimeError("settlement active pointer is missing")
            if active.generation_id != publication["generation_id"]:
                return False
        else:
            publication = verify_finalize_publication(session, finalize_job.job_id)
        children = _validated_daily_children_for_parent(session, parent)
        if any(child.status != "success" for child in children):
            return False
        required_parent = _required_parent_stage_for_finalize(session, parent)
        if required_parent is not None and required_parent.status != "success":
            return False
        parent_stage = session.scalar(
            select(JobStageRun).where(
                JobStageRun.job_id == parent_job_id,
                JobStageRun.stage_name == "finalize",
            )
        )
        if parent_stage is None:
            raise RuntimeError("range parent finalize stage is missing")
        now = datetime.now(UTC)
        parent_stage.status = "success"
        parent_stage.checkpoint_json = {
            **(parent_stage.checkpoint_json or {}),
            "finalize_job_id": finalize_job.job_id,
            **dict(publication),
            "stage": "finalize",
            "status": "success",
        }
        parent_stage.started_at = parent_stage.started_at or now
        parent_stage.finished_at = parent_stage.finished_at or now
        parent_stage.committed_at = parent_stage.committed_at or now
        parent_stage.updated_at = now
        parent.status = "success"
        parent.success_count = len(children)
        parent.failed_count = 0
        parent.finished_at = parent.finished_at or now
        parent.error_code = None
        parent.error_summary = None
        parent.error_message = None
        session.flush()
    return True


def reconcile_finalize_parents(session: Session, *, limit: int = 100) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 400:
        raise ValueError("finalize reconcile limit must be between 1 and 400")
    parent_ids = tuple(
        session.scalars(
            select(JobRun.parent_job_id)
            .where(
                JobRun.job_kind == "finalize",
                JobRun.status == "success",
                JobRun.parent_job_id.is_not(None),
            )
            .order_by(JobRun.parent_job_id)
            .limit(limit)
        )
    )
    promoted = 0
    for parent_id in parent_ids:
        if parent_id and promote_range_parent_if_ready(session, parent_id):
            promoted += 1
    return promoted


__all__ = [
    "FenceToken",
    "FinalizeInput",
    "StageFence",
    "promote_range_parent_if_ready",
    "reconcile_finalize_parents",
    "run_finalize_stage",
    "validate_finalize_input",
    "verify_finalize_publication",
]
