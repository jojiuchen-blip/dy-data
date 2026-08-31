"""Certification of the immutable legacy settlement root.

The certification deliberately writes only projection metadata.  Legacy
aggregate and score rows remain the authority and are never copied into an
overlay or sidecar table by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Iterator, Literal, Mapping, Sequence

from sqlalchemy import Boolean, Date, DateTime, Integer, JSON, Numeric, and_, delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    AggStoreMonthlySettlement,
    AggStoreRanking,
    SettlementProjectionActive,
    SettlementProjectionCompactionClosure,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    StoreScoreSnapshot,
    StoreScoreSnapshotRun,
)
from apps.worker.projection_lineage import (
    LineageError,
    canonical_score_partition_key,
    resolve_projection_partitions,
)


PROTOCOL = "t342b-legacy-null-root-v1"
PROJECTION = "settlement"
OPERATION = "legacy-null-root"
ARTIFACTS: tuple[str, str, str] = ("monthly", "ranking", "score")
COMPACTION_PROTOCOL = "t342d-metadata-compaction-v1"
COMPACTION_OPERATION = "metadata-compaction"
_CHECKPOINT_REQUIRED_KEYS = frozenset(
    {
        "protocol",
        "operation",
        "phase",
        "artifact",
        "cursor",
        "batch_count",
        "batch_size",
        "partition_count",
        "source_row_count",
        "estimated_manifest_rows",
        "estimated_write_bytes",
        "estimated_wal_bytes",
        "estimated_disk_headroom_bytes",
        "expected_active_pointer",
    }
)
MAX_BATCH_SIZE = 400
_FINAL_FENCE_DEADLINE_SECONDS = 5.0
_GENERATION_ADVISORY_LOCK_DEADLINE_SECONDS = 5.0
_MONTH_RE = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_AUDIT_COLUMNS = {
    "gmt_create",
    "gmt_modified",
    "created_at",
    "updated_at",
    "computed_at",
}


@dataclass(frozen=True)
class ResourceGateConfig:
    max_manifest_rows: int
    max_estimated_write_bytes: int
    max_estimated_wal_bytes: int
    observed_disk_headroom_bytes: int
    min_disk_headroom_bytes: int


@dataclass(frozen=True)
class CertificationResult:
    generation_id: str | None
    status: Literal["published", "already_published", "resource_guard"]
    published: bool
    resumed: bool
    batch_count: int
    partition_count: int
    source_row_count: int
    last_key: str | None
    manifest_checksum: str | None
    failure_code: str | None


@dataclass(frozen=True)
class CompactionThresholdConfig:
    minimum_lineage_depth: int
    batch_size: int = MAX_BATCH_SIZE


@dataclass(frozen=True)
class CompactionResult:
    generation_id: str | None
    status: Literal["not_needed", "ready", "already_ready", "resource_guard"]
    ready: bool
    resumed: bool
    base_generation_id: str
    batch_count: int
    partition_count: int
    source_generation_count: int
    last_key: str | None
    manifest_checksum: str | None
    failure_code: str | None


@dataclass(frozen=True)
class _CompactionPlanSummary:
    manifest_rows: int
    batch_count: int
    last_key: str | None
    effective_checksum: str


class LegacyProjectionBootstrapError(RuntimeError):
    """Fatal corruption, source drift, conflict, or publication failure."""


class _DifferentWinnerConflict(LegacyProjectionBootstrapError):
    """A different published generation owns the active settlement pointer."""


class _FenceTransientError(LegacyProjectionBootstrapError):
    """A bounded final-fence timeout that leaves the generation retryable."""


class _RetryScanPage(Exception):
    """Internal signal to discard a stale page and re-read durable progress."""


@dataclass
class _ScanStats:
    batch_count: int = 0
    partition_count: int = 0
    source_row_count: int = 0
    last_key: str | None = None


@dataclass
class _PartitionAccumulator:
    artifact: str
    partition_key: str
    row_count: int = 0
    amount_total_cent: int = 0
    status_counts: Counter[str] = field(default_factory=Counter)
    digest: str = ""
    last_key: str | None = None

    @classmethod
    def fresh(cls, artifact: str, partition_key: str) -> "_PartitionAccumulator":
        # A rolling digest keeps the checkpoint bounded even when a single
        # legacy partition contains millions of rows.  The digest is seeded by
        # the canonical empty row envelope and each subsequent row is appended
        # with an explicit length-free canonical JSON boundary.
        seed = _sha256(_canonical_json({"rows": []}))
        return cls(artifact=artifact, partition_key=partition_key, digest=seed)

    @classmethod
    def from_manifest(
        cls, artifact: str, partition_key: str, manifest: Mapping[str, Any]
    ) -> "_PartitionAccumulator":
        _validate_manifest_row(
            manifest, artifact, expected_partition_key=partition_key
        )
        status_raw = _normalize_status_counts(manifest.get("status_counts_json"))
        row_count = _strict_int(manifest.get("row_count"), "manifest row_count", nonnegative=True)
        amount = _strict_int(manifest.get("amount_total_cent"), "manifest amount_total_cent")
        checksum = manifest.get("checksum")
        return cls(
            artifact=artifact,
            partition_key=partition_key,
            row_count=row_count,
            amount_total_cent=amount,
            status_counts=Counter(status_raw),
            digest=checksum,
            last_key=manifest.get("last_key"),
        )

    def add(self, envelope: Mapping[str, Any], *, amount: int = 0, status: str | None = None) -> None:
        payload = _canonical_json(dict(envelope))
        self.digest = _sha256(bytes.fromhex(self.digest) + payload)
        self.row_count += 1
        self.amount_total_cent += int(amount)
        if status is not None:
            self.status_counts[str(status)] += 1

    def manifest_values(self) -> dict[str, Any]:
        return {
            "owner_state": "owned",
            "source_kind": "legacy_root",
            "data_generation_id": None,
            "base_generation_id": None,
            "row_count": self.row_count,
            "amount_total_cent": self.amount_total_cent,
            "status_counts_json": {
                key: self.status_counts[key] for key in sorted(self.status_counts)
            },
            "checksum": self.digest,
            "last_key": self.last_key,
        }


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value)
    stripped = value.strip()
    return stripped or None


def _reject_nonstandard_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON constant: {value}")


def _canonical_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            value = value.astimezone(timezone.utc)
            return value.isoformat().replace("+00:00", "Z")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        rendered = format(value, "f")
        if not rendered or Decimal(rendered) == 0:
            return "0"
        return rendered
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


def _mapped_value(column: Any, value: Any) -> Any:
    """Normalize values returned by untyped source SQL using mapped types.

    SQLite text() execution does not apply SQLAlchemy result processors, while
    PostgreSQL returns JSONB/date/numeric values in their native Python forms.
    Only columns whose mapped type is known are normalized here; ordinary
    strings are intentionally left untouched.
    """

    if value is None:
        return None
    mapped_type = column.type
    label = f"source column {column.name}"
    if isinstance(mapped_type, JSON):
        if isinstance(value, (str, bytes, bytearray)):
            try:
                value = json.loads(value, parse_constant=_reject_nonstandard_json_constant)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LegacyProjectionBootstrapError(f"{label} JSON is malformed") from exc
        if not isinstance(value, Mapping):
            raise LegacyProjectionBootstrapError(f"{label} JSON must be a mapping")
        return dict(value)
    if isinstance(mapped_type, DateTime):
        if isinstance(value, str):
            if value.strip() != value:
                raise LegacyProjectionBootstrapError(f"{label} datetime is not canonical")
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise LegacyProjectionBootstrapError(f"{label} datetime is malformed") from exc
        if not isinstance(value, datetime):
            raise LegacyProjectionBootstrapError(f"{label} datetime is malformed")
        if value.tzinfo is None:
            # SQLite's text() path loses timezone metadata for DateTime
            # columns; the model's timezone-aware contract treats that text as
            # UTC so it remains checksum-equivalent to PostgreSQL.
            value = value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(mapped_type, Date):
        if isinstance(value, str):
            if value.strip() != value:
                raise LegacyProjectionBootstrapError(f"{label} date is not canonical")
            try:
                value = date.fromisoformat(value)
            except ValueError as exc:
                raise LegacyProjectionBootstrapError(f"{label} date is malformed") from exc
        if isinstance(value, datetime) or not isinstance(value, date):
            raise LegacyProjectionBootstrapError(f"{label} date is malformed")
        return value
    if isinstance(mapped_type, Numeric):
        if isinstance(value, bool):
            raise LegacyProjectionBootstrapError(f"{label} numeric is malformed")
        if isinstance(value, str) and value.strip() != value:
            raise LegacyProjectionBootstrapError(f"{label} numeric is not canonical")
        try:
            value = value if isinstance(value, Decimal) else Decimal(str(value))
        except (TypeError, ValueError, ArithmeticError, InvalidOperation) as exc:
            raise LegacyProjectionBootstrapError(f"{label} numeric is malformed") from exc
        if not value.is_finite():
            raise LegacyProjectionBootstrapError(f"{label} numeric is non-finite")
        scale = getattr(mapped_type, "scale", None)
        if scale is None:
            value = value.normalize() if value else Decimal(0)
        else:
            try:
                quantizer = Decimal(1).scaleb(-int(scale))
                quantized = value.quantize(quantizer)
            except (InvalidOperation, ValueError, ArithmeticError) as exc:
                raise LegacyProjectionBootstrapError(f"{label} numeric is malformed") from exc
            if quantized != value:
                raise LegacyProjectionBootstrapError(f"{label} numeric exceeds mapped scale")
            value = quantized
        return value
    if isinstance(mapped_type, Boolean):
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in {0, 1}:
            return bool(value)
        if isinstance(value, str) and value in {"0", "1", "false", "true"}:
            return value in {"1", "true"}
        raise LegacyProjectionBootstrapError(f"{label} boolean is malformed")
    if isinstance(mapped_type, Integer):
        if isinstance(value, bool):
            raise LegacyProjectionBootstrapError(f"{label} integer is malformed")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip() == value:
            try:
                return int(value)
            except ValueError as exc:
                raise LegacyProjectionBootstrapError(f"{label} integer is malformed") from exc
        raise LegacyProjectionBootstrapError(f"{label} integer is malformed")
    return value


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            _canonical_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise LegacyProjectionBootstrapError("canonical JSON is malformed") from exc


_PROTOCOL_ENVELOPE: dict[str, Any] = {
    "protocol": PROTOCOL,
    "projection": PROJECTION,
    "operation": OPERATION,
    "artifacts": list(ARTIFACTS),
    "partition_key_version": "v1",
    "checksum_version": "v1",
}


def _input_fingerprint() -> str:
    return _sha256(_canonical_json(_PROTOCOL_ENVELOPE))


def _generation_id() -> str:
    return f"legacy-null-root:{_input_fingerprint()}"


def _empty_manifest_checksum() -> str:
    return _sha256(_canonical_json({**_PROTOCOL_ENVELOPE, "manifests": []}))


def _nonnegative_int(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise LegacyProjectionBootstrapError(f"{label} is invalid") from exc
    if result < 0:
        raise LegacyProjectionBootstrapError(f"{label} is negative")
    return result


def _nonnegative_or_signed_int(value: Any, label: str) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError) as exc:
        raise LegacyProjectionBootstrapError(f"{label} is invalid") from exc


def _strict_int(value: Any, label: str, *, nonnegative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LegacyProjectionBootstrapError(f"{label} is invalid")
    if nonnegative and value < 0:
        raise LegacyProjectionBootstrapError(f"{label} is negative")
    return value


def _strict_positive_int(value: Any, label: str) -> int:
    result = _strict_int(value, label)
    if result <= 0:
        raise LegacyProjectionBootstrapError(f"{label} is not positive")
    return result


def _normalize_status_counts(value: Any, *, label: str = "manifest status counts") -> dict[str, int]:
    if value is None:
        return {}
    if isinstance(value, (str, bytes, bytearray)):
        try:
            value = json.loads(value, parse_constant=_reject_nonstandard_json_constant)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LegacyProjectionBootstrapError(f"{label} are malformed") from exc
    if not isinstance(value, Mapping):
        raise LegacyProjectionBootstrapError(f"{label} are malformed")
    result: dict[str, int] = {}
    for key, count in value.items():
        if not isinstance(key, str) or key.strip() != key or not key:
            raise LegacyProjectionBootstrapError(f"{label} keys are malformed")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise LegacyProjectionBootstrapError(f"{label} values are malformed")
        result[key] = count
    return {key: result[key] for key in sorted(result)}


def _manifest_cursor_shape(artifact: str) -> tuple[str, ...]:
    required: dict[str, tuple[str, ...]] = {
        "monthly": (
            "month",
            "store_id",
            "product_scope",
            "product_type",
            "projection_run_id",
            "id",
        ),
        "ranking": (
            "period_type",
            "period_key",
            "store_id",
            "product_scope",
            "product_type",
            "projection_run_id",
            "id",
        ),
        "score": (
            "snapshot_date",
            "rule_version_id",
            "store_id",
            "snapshot_run_id",
            "snapshot_id",
        ),
    }
    return required[artifact]


def _validate_manifest_last_key(
    artifact: str, partition_key: str, row_count: int, last_key: Any
) -> str | None:
    if row_count == 0:
        if last_key is not None:
            raise LegacyProjectionBootstrapError("manifest last_key is invalid")
        return None
    if not isinstance(last_key, str) or last_key.strip() != last_key or not last_key:
        raise LegacyProjectionBootstrapError("manifest last_key is invalid")
    try:
        token = json.loads(last_key, parse_constant=_reject_nonstandard_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LegacyProjectionBootstrapError("manifest last_key is malformed") from exc
    if not isinstance(token, Mapping) or set(token) != {"artifact", "cursor"}:
        raise LegacyProjectionBootstrapError("manifest last_key is malformed")
    if token.get("artifact") != artifact or not isinstance(token.get("cursor"), Mapping):
        raise LegacyProjectionBootstrapError("manifest last_key is incompatible")
    cursor = token["cursor"]
    expected_keys = set(_manifest_cursor_shape(artifact))
    if set(cursor) != expected_keys:
        raise LegacyProjectionBootstrapError("manifest last_key is malformed")
    if any(cursor.get(key) is None for key in expected_keys):
        raise LegacyProjectionBootstrapError("manifest last_key is incomplete")
    if artifact == "monthly":
        _month_key(cursor.get("month"), label="manifest cursor month")
        for key in ("store_id", "product_scope", "product_type", "projection_run_id"):
            _identity(cursor.get(key), label=f"manifest cursor {key}")
        _strict_positive_int(cursor.get("id"), "manifest cursor id")
    elif artifact == "ranking":
        period_type = _strict_int(cursor.get("period_type"), "manifest cursor period_type")
        if period_type not in {1, 2}:
            raise LegacyProjectionBootstrapError("manifest cursor period_type is invalid")
        _month_key(cursor.get("period_key"), label="manifest cursor period_key")
        for key in ("store_id", "product_scope", "product_type", "projection_run_id"):
            _identity(cursor.get(key), label=f"manifest cursor {key}")
        _strict_positive_int(cursor.get("id"), "manifest cursor id")
    else:
        snapshot_date = cursor.get("snapshot_date")
        if not isinstance(snapshot_date, str) or snapshot_date.strip() != snapshot_date:
            raise LegacyProjectionBootstrapError("manifest cursor score date is invalid")
        try:
            date.fromisoformat(snapshot_date)
        except ValueError as exc:
            raise LegacyProjectionBootstrapError("manifest cursor score date is invalid") from exc
        _identity(cursor.get("rule_version_id"), label="manifest cursor rule_version_id")
        for key in ("store_id", "snapshot_run_id", "snapshot_id"):
            _identity(cursor.get(key), label=f"manifest cursor {key}")
    if _canonical_partition_from_cursor(artifact, cursor) != partition_key:
        raise LegacyProjectionBootstrapError("manifest cursor does not bind to partition key")
    if _cursor_token(artifact, dict(cursor)) != last_key:
        raise LegacyProjectionBootstrapError("manifest last_key is not canonical")
    return last_key


def _validate_manifest_row(
    row: Mapping[str, Any], artifact: str, *, expected_partition_key: str | None = None
) -> tuple[str, dict[str, int]]:
    if artifact not in ARTIFACTS or row.get("artifact") != artifact:
        raise LegacyProjectionBootstrapError("manifest artifact is invalid")
    partition_key = row.get("partition_key")
    if not isinstance(partition_key, str) or partition_key.strip() != partition_key:
        raise LegacyProjectionBootstrapError("manifest partition key is invalid")
    if expected_partition_key is not None and partition_key != expected_partition_key:
        raise LegacyProjectionBootstrapError("manifest partition key is incompatible")
    _canonical_partition_key(artifact, partition_key)
    if artifact == "monthly":
        _month_key(partition_key, label="manifest partition key")
    elif artifact == "ranking":
        match = re.fullmatch(r"(monthly|cumulative):([0-9]{4}-[0-9]{2})", partition_key)
        if match is None:
            raise LegacyProjectionBootstrapError("manifest partition key is invalid")
        _month_key(match.group(2), label="manifest partition month")
    else:
        score_parts = partition_key.split("|", 1)
        if len(score_parts) != 2:
            raise LegacyProjectionBootstrapError("manifest partition key is invalid")
        try:
            date.fromisoformat(score_parts[0])
        except ValueError as exc:
            raise LegacyProjectionBootstrapError("manifest partition key is invalid") from exc
        try:
            rule_length_raw, rule_and_store = score_parts[1].split(":", 1)
            rule_length = int(rule_length_raw)
        except (TypeError, ValueError) as exc:
            raise LegacyProjectionBootstrapError("manifest partition key is invalid") from exc
        if rule_length <= 0 or len(rule_and_store) <= rule_length or rule_and_store[rule_length] != "|":
            raise LegacyProjectionBootstrapError("manifest partition key is invalid")
        store_encoded = rule_and_store[rule_length + 1 :]
        try:
            store_length_raw, store_value = store_encoded.split(":", 1)
            store_length = int(store_length_raw)
        except (TypeError, ValueError) as exc:
            raise LegacyProjectionBootstrapError("manifest partition key is invalid") from exc
        if store_length <= 0 or store_length != len(store_value) or rule_length != len(rule_and_store[:rule_length]):
            raise LegacyProjectionBootstrapError("manifest partition key is invalid")
    if row.get("owner_state") != "owned":
        raise LegacyProjectionBootstrapError("manifest owner_state is invalid")
    if row.get("source_kind") != "legacy_root":
        raise LegacyProjectionBootstrapError("manifest source_kind is invalid")
    if row.get("data_generation_id") is not None or row.get("base_generation_id") is not None:
        raise LegacyProjectionBootstrapError("manifest generation lineage is invalid")
    row_count = _strict_int(row.get("row_count"), "manifest row_count", nonnegative=True)
    if row_count == 0:
        raise LegacyProjectionBootstrapError("manifest row_count must be positive")
    amount = row.get("amount_total_cent")
    _strict_int(amount, "manifest amount_total_cent")
    status_counts = _normalize_status_counts(row.get("status_counts_json"))
    if artifact == "monthly" and any(key not in {"1", "2", "3", "4"} for key in status_counts):
        raise LegacyProjectionBootstrapError("manifest status counts are invalid")
    if artifact == "monthly" and (
        not status_counts
        or any(count <= 0 for count in status_counts.values())
        or sum(status_counts.values()) != row_count
    ):
        raise LegacyProjectionBootstrapError("manifest status counts are inconsistent")
    if artifact != "monthly" and status_counts:
        raise LegacyProjectionBootstrapError("manifest status counts are invalid")
    if artifact == "score" and amount != 0:
        raise LegacyProjectionBootstrapError("score manifest amount_total_cent must be zero")
    checksum = row.get("checksum")
    if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
        raise LegacyProjectionBootstrapError("manifest checksum is invalid")
    _validate_manifest_last_key(artifact, partition_key, row_count, row.get("last_key"))
    return partition_key, status_counts


def _resource_guard(code: str) -> CertificationResult:
    return CertificationResult(
        generation_id=None,
        status="resource_guard",
        published=False,
        resumed=False,
        batch_count=0,
        partition_count=0,
        source_row_count=0,
        last_key=None,
        manifest_checksum=None,
        failure_code=code,
    )


def _validate_public_arguments(
    batch_size: int, resource_limits: ResourceGateConfig | None
) -> str | None:
    if isinstance(batch_size, bool) or not isinstance(batch_size, int):
        return "invalid_batch_size"
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        return "invalid_batch_size"
    if resource_limits is None:
        return "invalid_resource_config"
    for field_name in (
        "max_manifest_rows",
        "max_estimated_write_bytes",
        "max_estimated_wal_bytes",
        "observed_disk_headroom_bytes",
        "min_disk_headroom_bytes",
    ):
        value = getattr(resource_limits, field_name, None)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return "invalid_resource_config"
    if resource_limits.observed_disk_headroom_bytes < resource_limits.min_disk_headroom_bytes:
        return "invalid_resource_config"
    return None


def _open_session(session_factory: Callable[[], Session]) -> Session:
    try:
        session = session_factory()
    except Exception as exc:  # pragma: no cover - defensive factory boundary
        raise LegacyProjectionBootstrapError("failed to open database session") from exc
    if not hasattr(session, "execute") or not hasattr(session, "commit"):
        raise LegacyProjectionBootstrapError("session factory returned an invalid session")
    return session


def _close_session(session: Session) -> None:
    try:
        session.close()
    except Exception:
        pass


def _read_active_pointer(session_factory: Callable[[], Session]) -> str | None:
    session = _open_session(session_factory)
    try:
        row = session.execute(
            text(
                """
                SELECT a.generation_id AS pointer_generation_id,
                       g.generation_id AS target_generation_id,
                       g.projection_name AS target_projection_name,
                       g.state AS target_state
                FROM settlement_projection_active AS a
                LEFT JOIN settlement_projection_generation AS g
                  ON g.generation_id = a.generation_id
                WHERE a.projection_name = :projection_name
                """
            ),
            {"projection_name": PROJECTION},
        ).mappings().first()
        if row is None or row.get("pointer_generation_id") is None:
            return None
        pointer = _as_text(row.get("pointer_generation_id"))
        if (
            pointer is None
            or _as_text(row.get("target_generation_id")) != pointer
            or _as_text(row.get("target_projection_name")) != PROJECTION
            or _as_text(row.get("target_state")) != "published"
        ):
            raise LegacyProjectionBootstrapError(
                "settlement active pointer is dangling or not published"
            )
        return pointer
    except LegacyProjectionBootstrapError:
        raise
    except Exception as exc:
        raise LegacyProjectionBootstrapError("failed to read settlement active pointer") from exc
    finally:
        _close_session(session)


def _score_rule_expression(session: Session) -> Any:
    dialect = getattr(getattr(session, "bind", None), "dialect", None)
    name = getattr(dialect, "name", "sqlite")
    if name == "postgresql":
        return func.coalesce(
            func.nullif(func.btrim(StoreScoreSnapshotRun.config_json.op("->>")("rule_version_id")), ""),
            "legacy-unversioned",
        )
    return func.coalesce(
        func.nullif(
            func.trim(func.json_extract(StoreScoreSnapshotRun.config_json, "$.rule_version_id")),
            "",
        ),
        "legacy-unversioned",
    )


def _resource_preflight(
    session_factory: Callable[[], Session], limits: ResourceGateConfig
) -> tuple[int, int, int, int] | CertificationResult:
    session = _open_session(session_factory)
    try:
        monthly_rows = int(
            session.scalar(
                text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT month FROM agg_store_monthly_settlement GROUP BY month"
                    ") AS partitions"
                )
                )
            or 0
        )
        ranking_rows = int(
            session.scalar(
                text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT period_type, period_key FROM agg_store_ranking "
                    "GROUP BY period_type, period_key"
                    ") AS partitions"
                )
                )
            or 0
        )
        dialect = getattr(getattr(session, "bind", None), "dialect", None)
        dialect_name = getattr(dialect, "name", "sqlite")
        if dialect_name == "postgresql":
            rule_sql = (
                "COALESCE(NULLIF(BTRIM(r.config_json->>'rule_version_id'), ''), "
                "'legacy-unversioned')"
            )
        else:
            rule_sql = (
                "COALESCE(NULLIF(TRIM(json_extract(r.config_json, "
                "'$.rule_version_id')), ''), 'legacy-unversioned')"
            )
        score_rows = int(
            session.scalar(
                text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT s.snapshot_date, "
                    + rule_sql
                    + " AS rule_version_id, s.store_id "
                    "FROM store_score_snapshots AS s "
                    "JOIN store_score_snapshot_runs AS r "
                    "ON r.snapshot_run_id = s.snapshot_run_id "
                    "GROUP BY s.snapshot_date, "
                    + rule_sql
                    + ", s.store_id) AS partitions"
                )
            )
            or 0
        )
        invalid_score = session.scalar(
            text(
                "SELECT COUNT(*) FROM store_score_snapshots AS s "
                "LEFT JOIN store_score_snapshot_runs AS r "
                "ON r.snapshot_run_id = s.snapshot_run_id "
                "WHERE r.snapshot_run_id IS NULL "
                "OR s.snapshot_date IS NULL "
                "OR r.snapshot_date IS NULL "
                "OR s.snapshot_date <> r.snapshot_date"
            )
        )
        if int(invalid_score or 0) > 0:
            raise LegacyProjectionBootstrapError(
                "score snapshot has an orphan, date mismatch, or invalid identity"
            )
        manifest_rows = monthly_rows + ranking_rows + score_rows
        estimated_write_bytes = 16384 + (4096 * manifest_rows)
        estimated_wal_bytes = 2 * estimated_write_bytes
        available_headroom = (
            limits.observed_disk_headroom_bytes - limits.min_disk_headroom_bytes
        )
        if manifest_rows > limits.max_manifest_rows:
            return _resource_guard("manifest_rows_exceed_limit")
        if estimated_write_bytes > limits.max_estimated_write_bytes:
            return _resource_guard("estimated_write_bytes_exceed_limit")
        if estimated_wal_bytes > limits.max_estimated_wal_bytes:
            return _resource_guard("estimated_wal_bytes_exceed_limit")
        if available_headroom < estimated_write_bytes + estimated_wal_bytes:
            return _resource_guard("disk_headroom_insufficient")
        return (
            manifest_rows,
            estimated_write_bytes,
            estimated_wal_bytes,
            available_headroom,
        )
    except LegacyProjectionBootstrapError:
        raise
    except Exception as exc:
        raise LegacyProjectionBootstrapError("resource preflight failed") from exc
    finally:
        _close_session(session)


def _preflight_source_integrity(
    session_factory: Callable[[], Session], batch_size: int
) -> None:
    """Reject invalid legacy identities before creating certification metadata.

    This pass is deliberately read-only and page-bounded.  It validates every
    monthly/ranking row through the same partition helpers used by the scan,
    while the score orphan/date check below also covers rows that an inner join
    would otherwise hide from the normal score keyset reader.
    """

    session = _open_session(session_factory)
    try:
        invalid_score = session.scalar(
            text(
                "SELECT 1 FROM store_score_snapshots AS s "
                "LEFT JOIN store_score_snapshot_runs AS r "
                "ON r.snapshot_run_id = s.snapshot_run_id "
                "WHERE r.snapshot_run_id IS NULL "
                "OR s.snapshot_date IS NULL "
                "OR r.snapshot_date IS NULL "
                "OR s.snapshot_date <> r.snapshot_date "
                "LIMIT :integrity_limit"
            ),
            {"integrity_limit": 1},
        )
    except Exception as exc:
        raise LegacyProjectionBootstrapError(
            "score source integrity preflight failed"
        ) from exc
    finally:
        _close_session(session)
    if invalid_score is not None:
        raise LegacyProjectionBootstrapError(
            "score snapshot has an orphan, date mismatch, or invalid identity"
        )

    for artifact in ARTIFACTS:
        cursor: Mapping[str, Any] | None = None
        while True:
            session = _open_session(session_factory)
            try:
                page = _select_source_page(session, artifact, batch_size, cursor)
            finally:
                _close_session(session)
            if not page:
                break
            for raw in page:
                if artifact == "monthly":
                    _row_mapping(raw, _source_columns(AggStoreMonthlySettlement))
                    _monthly_partition(raw)
                elif artifact == "ranking":
                    _row_mapping(raw, _source_columns(AggStoreRanking))
                    _ranking_partition(raw)
                else:
                    _row_mapping(raw, _source_columns(StoreScoreSnapshot))
                    _score_partition(raw)
                _cursor_from_row(artifact, raw)
            cursor = _cursor_from_row(artifact, page[-1])


def _source_columns(model: Any) -> list[Any]:
    return [
        column
        for column in model.__table__.columns
        if column.name != "id" and column.name not in _AUDIT_COLUMNS
    ]


def _month_key(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or value.strip() != value or not _MONTH_RE.fullmatch(value):
        raise LegacyProjectionBootstrapError(f"{label} is not canonical YYYY-MM")
    try:
        date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise LegacyProjectionBootstrapError(f"{label} is not a valid month") from exc
    return value


def _identity(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or value.strip() != value or not value:
        raise LegacyProjectionBootstrapError(f"{label} is not a canonical identity")
    return value


def _strict_score_date(value: Any, *, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or value.strip() != value:
        raise LegacyProjectionBootstrapError(f"{label} is not canonical ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise LegacyProjectionBootstrapError(f"{label} is not canonical ISO date") from exc
    if parsed.isoformat() != value:
        raise LegacyProjectionBootstrapError(f"{label} is not canonical ISO date")
    return parsed


def _canonical_partition_key(artifact: str, partition_key: Any) -> str:
    """Validate and return one canonical partition key for any artifact."""

    if artifact == "monthly":
        return _month_key(partition_key, label="monthly partition key")
    if artifact == "ranking":
        if not isinstance(partition_key, str):
            raise LegacyProjectionBootstrapError("ranking partition key is invalid")
        match = re.fullmatch(r"(monthly|cumulative):([0-9]{4}-[0-9]{2})", partition_key)
        if match is None:
            raise LegacyProjectionBootstrapError("ranking partition key is invalid")
        period_key = _month_key(match.group(2), label="ranking partition month")
        return f"{match.group(1)}:{period_key}"
    if artifact != "score" or not isinstance(partition_key, str):
        raise LegacyProjectionBootstrapError("score partition key is invalid")
    date_separator = partition_key.find("|")
    if date_separator <= 0:
        raise LegacyProjectionBootstrapError("score partition key is invalid")
    snapshot_date = _strict_score_date(
        partition_key[:date_separator], label="score partition date"
    )
    encoded_identities = partition_key[date_separator + 1 :]
    rule_match = re.match(r"([1-9][0-9]*):", encoded_identities)
    if rule_match is None:
        raise LegacyProjectionBootstrapError("score partition key is invalid")
    try:
        rule_length = int(rule_match.group(1))
    except (ValueError, OverflowError) as exc:
        raise LegacyProjectionBootstrapError("score partition key length is invalid") from exc
    rule_start = rule_match.end()
    rule_end = rule_start + rule_length
    if rule_end >= len(encoded_identities) or encoded_identities[rule_end] != "|":
        raise LegacyProjectionBootstrapError("score partition key is invalid")
    rule_id = encoded_identities[rule_start:rule_end]
    store_section = encoded_identities[rule_end + 1 :]
    store_match = re.match(r"([1-9][0-9]*):", store_section)
    if store_match is None:
        raise LegacyProjectionBootstrapError("score partition key is invalid")
    try:
        store_length = int(store_match.group(1))
    except (ValueError, OverflowError) as exc:
        raise LegacyProjectionBootstrapError("score partition key length is invalid") from exc
    store_start = store_match.end()
    store_end = store_start + store_length
    if store_end != len(store_section):
        raise LegacyProjectionBootstrapError("score partition key is invalid")
    store_id = store_section[store_start:store_end]
    _identity(rule_id, label="score partition rule_version_id")
    _identity(store_id, label="score partition store_id")
    expected = canonical_score_partition_key(snapshot_date, rule_id, store_id)
    if expected != partition_key:
        raise LegacyProjectionBootstrapError("score partition key is not canonical")
    return expected


def _canonical_partition_from_cursor(
    artifact: str, cursor: Mapping[str, Any]
) -> str:
    required = set(_manifest_cursor_shape(artifact))
    if set(cursor) != required or any(cursor.get(key) is None for key in required):
        raise LegacyProjectionBootstrapError("cursor is incomplete or malformed")
    if artifact == "monthly":
        month = _month_key(cursor.get("month"), label="monthly cursor month")
        for key in ("store_id", "product_scope", "product_type", "projection_run_id"):
            _identity(cursor.get(key), label=f"monthly cursor {key}")
        _strict_positive_int(cursor.get("id"), "monthly cursor id")
        return month
    if artifact == "ranking":
        period_type = _strict_int(cursor.get("period_type"), "ranking cursor period_type")
        if period_type not in {1, 2}:
            raise LegacyProjectionBootstrapError("ranking cursor period_type is invalid")
        period_key = _month_key(cursor.get("period_key"), label="ranking cursor period_key")
        for key in ("store_id", "product_scope", "product_type", "projection_run_id"):
            _identity(cursor.get(key), label=f"ranking cursor {key}")
        _strict_positive_int(cursor.get("id"), "ranking cursor id")
        return f"{'monthly' if period_type == 1 else 'cumulative'}:{period_key}"
    snapshot_date = _strict_score_date(
        cursor.get("snapshot_date"), label="score cursor date"
    )
    rule_id = _identity(cursor.get("rule_version_id"), label="score cursor rule_version_id")
    store_id = _identity(cursor.get("store_id"), label="score cursor store_id")
    _identity(cursor.get("snapshot_run_id"), label="score cursor snapshot_run_id")
    _identity(cursor.get("snapshot_id"), label="score cursor snapshot_id")
    return canonical_score_partition_key(snapshot_date, rule_id, store_id)


def _row_mapping(row: Mapping[str, Any], columns: list[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in columns:
        result[column.name] = _mapped_value(column, row.get(column.name))
    return result


def _monthly_partition(row: Mapping[str, Any]) -> str:
    month = _month_key(row.get("month"), label="monthly month")
    _identity(row.get("store_id"), label="monthly store_id")
    _identity(row.get("product_scope"), label="monthly product_scope")
    _identity(row.get("product_type"), label="monthly product_type")
    _identity(row.get("projection_run_id"), label="monthly projection_run_id")
    if row.get("statement_status") is None:
        raise LegacyProjectionBootstrapError("monthly statement_status is NULL")
    status = _strict_int(row.get("statement_status"), "monthly statement_status")
    if status not in {1, 2, 3, 4}:
        raise LegacyProjectionBootstrapError("monthly statement_status is invalid")
    return month


def _ranking_partition(row: Mapping[str, Any]) -> str:
    period_type = row.get("period_type")
    period_type_int = _strict_int(period_type, "ranking period_type")
    if period_type_int not in {1, 2}:
        raise LegacyProjectionBootstrapError("ranking period_type is invalid")
    period_key = _month_key(row.get("period_key"), label="ranking period_key")
    if _as_text(row.get("month")) != period_key:
        raise LegacyProjectionBootstrapError("ranking month does not match period_key")
    _identity(row.get("store_id"), label="ranking store_id")
    _identity(row.get("product_scope"), label="ranking product_scope")
    _identity(row.get("product_type"), label="ranking product_type")
    _identity(row.get("projection_run_id"), label="ranking projection_run_id")
    return f"{'monthly' if period_type_int == 1 else 'cumulative'}:{period_key}"


def _score_partition(row: Mapping[str, Any]) -> str:
    snapshot_id = _identity(row.get("snapshot_id"), label="score snapshot_id")
    run_id = _identity(row.get("snapshot_run_id"), label="score snapshot_run_id")
    store_id = _identity(row.get("store_id"), label="score store_id")
    snapshot_date = row.get("snapshot_date")
    run_snapshot_date = row.get("run_snapshot_date")
    if snapshot_date is None or run_snapshot_date is None:
        raise LegacyProjectionBootstrapError("score snapshot_date is NULL")
    snapshot_date = _strict_score_date(snapshot_date, label="score snapshot_date")
    run_snapshot_date = _strict_score_date(
        run_snapshot_date, label="score run snapshot_date"
    )
    if snapshot_date != run_snapshot_date:
        raise LegacyProjectionBootstrapError("score snapshot/run date mismatch")
    rule_raw = row.get("rule_version_id")
    if rule_raw is None:
        rule_id = "legacy-unversioned"
    else:
        rule_id = _identity(rule_raw, label="score rule_version_id")
    # Keep these identities in the checksum envelope even though only the
    # partition key itself is returned here.
    _ = snapshot_id, run_id
    return canonical_score_partition_key(snapshot_date, rule_id, store_id)


def _cursor_token(artifact: str, cursor: Mapping[str, Any]) -> str:
    return _canonical_json({"artifact": artifact, "cursor": cursor}).decode("utf-8")


def _cursor_from_row(artifact: str, row: Mapping[str, Any]) -> dict[str, Any]:
    def source_id(value: Any) -> int:
        return _strict_positive_int(value, "source cursor id")

    if artifact == "monthly":
        return {
            "month": row.get("month"),
            "store_id": row.get("store_id"),
            "product_scope": row.get("product_scope"),
            "product_type": row.get("product_type"),
            "projection_run_id": row.get("projection_run_id"),
            "id": source_id(row.get("id")),
        }
    if artifact == "ranking":
        return {
            "period_type": _strict_int(row.get("period_type"), "source cursor period_type"),
            "period_key": row.get("period_key"),
            "store_id": row.get("store_id"),
            "product_scope": row.get("product_scope"),
            "product_type": row.get("product_type"),
            "projection_run_id": row.get("projection_run_id"),
            "id": source_id(row.get("id")),
        }
    snapshot_date = _strict_score_date(
        row.get("snapshot_date"), label="score cursor date"
    ).isoformat()
    rule_raw = row.get("rule_version_id")
    rule_id = "legacy-unversioned" if rule_raw is None else _identity(
        rule_raw, label="score cursor rule_version_id"
    )
    cursor = {
        "snapshot_date": snapshot_date,
        "rule_version_id": rule_id,
        "store_id": _identity(row.get("store_id"), label="score cursor store_id"),
        "snapshot_run_id": _identity(
            row.get("snapshot_run_id"), label="score cursor snapshot_run_id"
        ),
        "snapshot_id": _identity(row.get("snapshot_id"), label="score cursor snapshot_id"),
    }
    _canonical_partition_from_cursor("score", cursor)
    return cursor


def _cursor_order_key(artifact: str, cursor: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the same lexicographic key used by each artifact's keyset SQL."""

    if artifact == "monthly":
        return (
            cursor.get("month"),
            cursor.get("store_id"),
            cursor.get("product_scope"),
            cursor.get("product_type"),
            cursor.get("projection_run_id"),
            int(cursor.get("id")),
        )
    if artifact == "ranking":
        return (
            int(cursor.get("period_type")),
            cursor.get("period_key"),
            cursor.get("store_id"),
            cursor.get("product_scope"),
            cursor.get("product_type"),
            cursor.get("projection_run_id"),
            int(cursor.get("id")),
        )
    return (
        cursor.get("snapshot_date"),
        cursor.get("rule_version_id"),
        cursor.get("store_id"),
        cursor.get("snapshot_run_id"),
        cursor.get("snapshot_id"),
    )


def _cursor_condition(artifact: str, row: Mapping[str, Any], cursor: Mapping[str, Any]) -> Any:
    if artifact == "monthly":
        keys = (
            (AggStoreMonthlySettlement.month, cursor.get("month")),
            (AggStoreMonthlySettlement.store_id, cursor.get("store_id")),
            (AggStoreMonthlySettlement.product_scope, cursor.get("product_scope")),
            (AggStoreMonthlySettlement.product_type, cursor.get("product_type")),
            (AggStoreMonthlySettlement.projection_run_id, cursor.get("projection_run_id")),
            (AggStoreMonthlySettlement.id, cursor.get("id")),
        )
    elif artifact == "ranking":
        keys = (
            (AggStoreRanking.period_type, cursor.get("period_type")),
            (AggStoreRanking.period_key, cursor.get("period_key")),
            (AggStoreRanking.store_id, cursor.get("store_id")),
            (AggStoreRanking.product_scope, cursor.get("product_scope")),
            (AggStoreRanking.product_type, cursor.get("product_type")),
            (AggStoreRanking.projection_run_id, cursor.get("projection_run_id")),
            (AggStoreRanking.id, cursor.get("id")),
        )
    else:
        # Score ordering uses the normalized SQL rule expression.  The extra
        # expression is passed as ``row`` by the caller.
        rule_expr = row["__rule_expr"]
        snapshot_cursor = cursor.get("snapshot_date")
        if isinstance(snapshot_cursor, str):
            try:
                snapshot_cursor = date.fromisoformat(snapshot_cursor)
            except ValueError as exc:
                raise LegacyProjectionBootstrapError("score checkpoint date is invalid") from exc
        keys = (
            (StoreScoreSnapshot.snapshot_date, snapshot_cursor),
            (rule_expr, cursor.get("rule_version_id")),
            (StoreScoreSnapshot.store_id, cursor.get("store_id")),
            (StoreScoreSnapshot.snapshot_run_id, cursor.get("snapshot_run_id")),
            (StoreScoreSnapshot.snapshot_id, cursor.get("snapshot_id")),
        )
    clauses: list[Any] = []
    equals: list[Any] = []
    for column, value in keys:
        clauses.append(and_(*equals, column > value) if equals else column > value)
        equals.append(column == value)
    return or_(*clauses)


def _select_source_page(
    session: Session,
    artifact: str,
    batch_size: int,
    cursor: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    def keyset_clause(
        columns: tuple[str, ...], values: tuple[Any, ...]
    ) -> tuple[str, dict[str, Any]]:
        if not values:
            return "", {"page_limit": batch_size}
        params: dict[str, Any] = {"page_limit": batch_size}
        clauses: list[str] = []
        for index, (column, value) in enumerate(zip(columns, values)):
            equals: list[str] = []
            for previous in range(index):
                name = f"cursor_{previous}"
                equals.append(f"{columns[previous]} = :{name}")
                params[name] = values[previous]
            name = f"cursor_{index}"
            params[name] = value
            prefix = " AND ".join(equals)
            clauses.append(f"({prefix + ' AND ' if prefix else ''}{column} > :{name})")
        null_guard = " OR ".join(f"{column} IS NULL" for column in columns)
        return "WHERE (" + " OR ".join(clauses) + ") OR (" + null_guard + ")", params

    if artifact == "monthly":
        columns = _source_columns(AggStoreMonthlySettlement)
        names = [column.name for column in columns]
        order_names = (
            "month",
            "store_id",
            "product_scope",
            "product_type",
            "projection_run_id",
            "id",
        )
        values = (
            cursor.get("month"),
            cursor.get("store_id"),
            cursor.get("product_scope"),
            cursor.get("product_type"),
            cursor.get("projection_run_id"),
            cursor.get("id"),
        ) if cursor else ()
        where, params = keyset_clause(order_names, values)
        statement = text(
            f"SELECT id, {', '.join(names)} FROM agg_store_monthly_settlement "
            f"{where} ORDER BY {', '.join(f'{name} NULLS LAST' for name in order_names)} LIMIT :page_limit"
        )
    elif artifact == "ranking":
        columns = _source_columns(AggStoreRanking)
        names = [column.name for column in columns]
        order_names = (
            "period_type",
            "period_key",
            "store_id",
            "product_scope",
            "product_type",
            "projection_run_id",
            "id",
        )
        values = (
            cursor.get("period_type"),
            cursor.get("period_key"),
            cursor.get("store_id"),
            cursor.get("product_scope"),
            cursor.get("product_type"),
            cursor.get("projection_run_id"),
            cursor.get("id"),
        ) if cursor else ()
        where, params = keyset_clause(order_names, values)
        statement = text(
            f"SELECT id, {', '.join(names)} FROM agg_store_ranking "
            f"{where} ORDER BY {', '.join(f'{name} NULLS LAST' for name in order_names)} LIMIT :page_limit"
        )
    else:
        columns = _source_columns(StoreScoreSnapshot)
        names = [f"s.{column.name}" for column in columns]
        dialect_name = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
        if dialect_name == "postgresql":
            rule_expr = (
                "COALESCE(NULLIF(BTRIM(r.config_json->>'rule_version_id'), ''), "
                "'legacy-unversioned')"
            )
        else:
            rule_expr = (
                "COALESCE(NULLIF(TRIM(json_extract(r.config_json, "
                "'$.rule_version_id')), ''), 'legacy-unversioned')"
            )
        order_names = (
            "s.snapshot_date",
            "rule_version_id",
            "s.store_id",
            "s.snapshot_run_id",
            "s.snapshot_id",
        )
        cursor_names = (
            "s.snapshot_date",
            rule_expr,
            "s.store_id",
            "s.snapshot_run_id",
            "s.snapshot_id",
        )
        values = ()
        if cursor:
            snapshot_cursor = cursor.get("snapshot_date")
            if isinstance(snapshot_cursor, str):
                try:
                    snapshot_cursor = date.fromisoformat(snapshot_cursor)
                except ValueError as exc:
                    raise LegacyProjectionBootstrapError(
                        "score checkpoint date is invalid"
                    ) from exc
            values = (
                snapshot_cursor,
                cursor.get("rule_version_id"),
                cursor.get("store_id"),
                cursor.get("snapshot_run_id"),
                cursor.get("snapshot_id"),
            )
        where, params = keyset_clause(cursor_names, values)
        statement = text(
            f"SELECT {', '.join(names)}, r.snapshot_date AS run_snapshot_date, "
            f"{rule_expr} AS rule_version_id FROM store_score_snapshots AS s "
            f"LEFT JOIN store_score_snapshot_runs AS r ON r.snapshot_run_id = s.snapshot_run_id "
            f"{where} ORDER BY {', '.join(f'{name} NULLS LAST' for name in order_names)} LIMIT :page_limit"
        )
    rows = session.execute(statement, params).mappings().all()
    return [dict(row) for row in rows]


def _load_manifests_for_keys(
    session: Session,
    generation_id: str,
    artifact: str,
    keys: list[str],
) -> dict[str, dict[str, Any]]:
    if not keys:
        return {}
    table = SettlementProjectionPartitionManifest.__table__
    rows = session.execute(
        select(*table.columns).where(
            SettlementProjectionPartitionManifest.generation_id == generation_id,
            SettlementProjectionPartitionManifest.artifact == artifact,
            SettlementProjectionPartitionManifest.partition_key.in_(keys),
        )
    ).mappings().all()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        mapping = dict(row)
        key = _as_text(mapping.get("partition_key"))
        if key is None or key in result:
            raise LegacyProjectionBootstrapError("duplicate or malformed partition manifest")
        result[key] = mapping
    return result


def _validate_existing_manifest_prefix(
    session_factory: Callable[[], Session],
    artifact: str,
    manifest: Mapping[str, Any],
    batch_size: int,
) -> None:
    """Recompute a resumed manifest prefix before allowing an upsert.

    A checkpoint cursor proves where the next page starts, but it does not by
    itself prove that an existing manifest's row count, totals, status counts,
    and checksum describe the committed source prefix.  Recompute that prefix
    with the same bounded keyset reader so incompatible metadata fails closed
    before a resumed page can overwrite it.
    """

    expected = _PartitionAccumulator.from_manifest(
        artifact,
        _as_text(manifest.get("partition_key")) or "",
        manifest,
    )
    target_partition = expected.partition_key
    target_last_key = expected.last_key
    if target_last_key is None:
        raise LegacyProjectionBootstrapError(
            "existing manifest has no durable source cursor"
        )
    cursor: Mapping[str, Any] | None = None
    actual = _PartitionAccumulator.fresh(artifact, target_partition)
    found = False
    while True:
        session = _open_session(session_factory)
        try:
            page = _select_source_page(session, artifact, batch_size, cursor)
        finally:
            _close_session(session)
        if not page:
            break
        for raw in page:
            if artifact == "monthly":
                partition_key = _monthly_partition(raw)
                envelope = _row_mapping(raw, _source_columns(AggStoreMonthlySettlement))
                amount = int(raw.get("promotion_net_fee_cent") or 0) - int(
                    raw.get("management_net_fee_cent") or 0
                )
                status = str(_strict_int(raw.get("statement_status"), "monthly statement_status"))
            elif artifact == "ranking":
                partition_key = _ranking_partition(raw)
                envelope = _row_mapping(raw, _source_columns(AggStoreRanking))
                amount = int(raw.get("net_settlement_reference_cent") or 0)
                status = None
            else:
                partition_key = _score_partition(raw)
                envelope = _row_mapping(raw, _source_columns(StoreScoreSnapshot))
                amount = 0
                status = None
            row_cursor = _cursor_from_row(artifact, raw)
            token = _cursor_token(artifact, row_cursor)
            if partition_key == target_partition:
                actual.add(envelope, amount=amount, status=status)
                actual.last_key = token
            if token == target_last_key:
                found = True
                break
        if found:
            break
        cursor = _cursor_from_row(artifact, page[-1])
    if not found:
        raise LegacyProjectionBootstrapError(
            "existing manifest cursor is not present in source"
        )
    if (
        expected.row_count != actual.row_count
        or expected.amount_total_cent != actual.amount_total_cent
        or dict(expected.status_counts) != dict(actual.status_counts)
        or expected.digest != actual.digest
        or expected.last_key != actual.last_key
    ):
        raise LegacyProjectionBootstrapError(
            "existing manifest metadata conflicts with source prefix"
        )


def _validate_existing_manifests_prefix_once(
    session_factory: Callable[[], Session],
    generation_id: str,
    artifact: str,
    batch_size: int,
    durable_cursor: Mapping[str, Any],
    max_manifest_rows: int,
) -> None:
    """Validate all committed manifests through one durable source prefix.

    A resumed/adopted checkpoint is validated once as a global prefix.  The
    writer then starts strictly after ``durable_cursor``; it never replays a
    per-partition prefix scan for every subsequent page.
    """

    manifests = _fetch_all_generation_manifests(
        session_factory,
        generation_id,
        artifact,
        max_manifest_rows=max_manifest_rows,
    )
    if not manifests:
        return
    target_token = _cursor_token(artifact, durable_cursor)
    target_order = _cursor_order_key(artifact, durable_cursor)
    expected: dict[str, _PartitionAccumulator] = {}
    for row in manifests:
        partition_key, _status_counts = _validate_manifest_row(row, artifact)
        manifest_last_key = row.get("last_key")
        try:
            manifest_token = json.loads(
                str(manifest_last_key), parse_constant=_reject_nonstandard_json_constant
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LegacyProjectionBootstrapError("manifest last_key is malformed") from exc
        manifest_cursor = manifest_token.get("cursor") if isinstance(manifest_token, Mapping) else None
        if not isinstance(manifest_cursor, Mapping):
            raise LegacyProjectionBootstrapError("manifest last_key is malformed")
        if _cursor_order_key(artifact, manifest_cursor) > target_order:
            # A peer may have committed later pages before this verifier
            # adopted an earlier durable checkpoint.  Do not compare those
            # future manifests against the bounded source prefix.
            continue
        if partition_key in expected:
            raise LegacyProjectionBootstrapError("duplicate or malformed partition manifest")
        expected[partition_key] = _PartitionAccumulator.from_manifest(
            artifact, partition_key, row
        )
    actual: dict[str, _PartitionAccumulator] = {}
    cursor: Mapping[str, Any] | None = None
    found = False
    while True:
        session = _open_session(session_factory)
        try:
            page = _select_source_page(session, artifact, batch_size, cursor)
        finally:
            _close_session(session)
        if not page:
            break
        for raw in page:
            if artifact == "monthly":
                partition_key = _monthly_partition(raw)
                envelope = _row_mapping(raw, _source_columns(AggStoreMonthlySettlement))
                amount = int(raw.get("promotion_net_fee_cent") or 0) - int(
                    raw.get("management_net_fee_cent") or 0
                )
                status = str(_strict_int(raw.get("statement_status"), "monthly statement_status"))
            elif artifact == "ranking":
                partition_key = _ranking_partition(raw)
                envelope = _row_mapping(raw, _source_columns(AggStoreRanking))
                amount = int(raw.get("net_settlement_reference_cent") or 0)
                status = None
            else:
                partition_key = _score_partition(raw)
                envelope = _row_mapping(raw, _source_columns(StoreScoreSnapshot))
                amount = 0
                status = None
            if partition_key not in expected:
                raise LegacyProjectionBootstrapError(
                    "source prefix has no certified manifest"
                )
            accumulator = actual.get(partition_key)
            if accumulator is None:
                accumulator = _PartitionAccumulator.fresh(artifact, partition_key)
                actual[partition_key] = accumulator
            accumulator.add(envelope, amount=amount, status=status)
            row_token = _cursor_token(artifact, _cursor_from_row(artifact, raw))
            accumulator.last_key = row_token
            if row_token == target_token:
                found = True
                break
        if found:
            break
        cursor = _cursor_from_row(artifact, page[-1])
    if not found:
        raise LegacyProjectionBootstrapError(
            "durable checkpoint cursor is not present in source"
        )
    for partition_key, expected_accumulator in expected.items():
        actual_accumulator = actual.get(partition_key)
        if actual_accumulator is None or (
            expected_accumulator.row_count != actual_accumulator.row_count
            or expected_accumulator.amount_total_cent
            != actual_accumulator.amount_total_cent
            or dict(expected_accumulator.status_counts)
            != dict(actual_accumulator.status_counts)
            or expected_accumulator.digest != actual_accumulator.digest
            or expected_accumulator.last_key != actual_accumulator.last_key
        ):
            raise LegacyProjectionBootstrapError(
                "existing manifest metadata conflicts with source prefix"
            )


def _manifest_payload(
    generation_id: str,
    artifact: str,
    partition_key: str,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "generation_id": generation_id,
        "artifact": artifact,
        "partition_key": partition_key,
        **dict(values),
    }


def _upsert_manifests(session: Session, payloads: list[dict[str, Any]]) -> None:
    if not payloads:
        return
    dialect_name = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    table = SettlementProjectionPartitionManifest.__table__
    statement = dialect_insert(table).values(payloads)
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.generation_id, table.c.artifact, table.c.partition_key],
        set_={
            "owner_state": excluded.owner_state,
            "source_kind": excluded.source_kind,
            "data_generation_id": excluded.data_generation_id,
            "base_generation_id": excluded.base_generation_id,
            "row_count": excluded.row_count,
            "amount_total_cent": excluded.amount_total_cent,
            "status_counts_json": excluded.status_counts_json,
            "checksum": excluded.checksum,
            "last_key": excluded.last_key,
        },
    )
    session.execute(statement)


def _checkpoint(
    *,
    phase: str,
    artifact: str | None,
    cursor: Mapping[str, Any] | None,
    stats: _ScanStats,
    resource: tuple[int, int, int, int],
    batch_size: int = MAX_BATCH_SIZE,
) -> dict[str, Any]:
    rows, write_bytes, wal_bytes, headroom = resource
    return {
        "protocol": PROTOCOL,
        "operation": OPERATION,
        "phase": phase,
        "artifact": artifact,
        "cursor": dict(cursor) if cursor is not None else None,
        "batch_count": stats.batch_count,
        "batch_size": batch_size,
        "partition_count": stats.partition_count,
        "source_row_count": stats.source_row_count,
        "estimated_manifest_rows": rows,
        "estimated_write_bytes": write_bytes,
        "estimated_wal_bytes": wal_bytes,
        "estimated_disk_headroom_bytes": headroom,
        "expected_active_pointer": None,
    }


def _update_generation(
    session_factory: Callable[[], Session],
    generation_id: str,
    *,
    state: str | None = None,
    checkpoint: Mapping[str, Any] | None = None,
    last_key: str | None = None,
    manifest_checksum: str | None = None,
    failure_code: str | None = None,
    failure_reason: str | None = None,
) -> None:
    values: dict[str, Any] = {}
    if state is not None:
        values["state"] = state
    if checkpoint is not None:
        values["checkpoint_json"] = dict(checkpoint)
    if last_key is not None or checkpoint is not None:
        values["last_key"] = last_key
    if manifest_checksum is not None:
        values["manifest_checksum"] = manifest_checksum
    if failure_code is not None:
        values["failure_code"] = failure_code
        values["failure_reason"] = failure_reason
        values["failed_at"] = datetime.now(timezone.utc)
    if state == "published":
        values["published_at"] = datetime.now(timezone.utc)
    if not values:
        return
    session = _open_session(session_factory)
    try:
        statement = update(SettlementProjectionGeneration).where(
            SettlementProjectionGeneration.generation_id == generation_id
        )
        # A concurrent certifier may have published the deterministic root
        # while this invocation was still scanning.  Checkpoint writes from
        # that stale invocation must never regress the durable state back to
        # ``ready`` (or ``staging``); the publication CAS owns the terminal
        # transition.
        if state in {"staging", "ready", "failed"}:
            statement = statement.where(
                SettlementProjectionGeneration.state.in_(("staging", "ready"))
            )
        session.execute(statement.values(**values))
        session.commit()
    except Exception:
        try:
            session.rollback()
        finally:
            _close_session(session)
        raise
    _close_session(session)


def _promote_staging_to_ready(
    session_factory: Callable[[], Session], generation_id: str
) -> SettlementProjectionGeneration:
    """Promote only the currently durable terminal scan checkpoint.

    The caller deliberately supplies no checkpoint or last-key value.  A
    short transaction re-reads the row under the SQLite writer lock (or a
    PostgreSQL row lock), so a stale verifier can only adopt the peer's
    current terminal value and never write its locally captured checkpoint.
    """

    session = _open_session(session_factory)
    try:
        dialect_name = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
        if dialect_name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        statement = select(SettlementProjectionGeneration).where(
            SettlementProjectionGeneration.generation_id == generation_id
        )
        if dialect_name == "postgresql":
            statement = statement.with_for_update()
        generation = session.execute(statement).scalar_one_or_none()
        if generation is None:
            raise LegacyProjectionBootstrapError("generation disappeared before ready transition")
        if generation.state in {"ready", "published"}:
            session.commit()
            session.refresh(generation)
            session.expunge(generation)
            return generation
        if generation.state != "staging":
            raise LegacyProjectionBootstrapError("generation state is incompatible for ready transition")
        checkpoint = generation.checkpoint_json
        if not isinstance(checkpoint, Mapping):
            raise LegacyProjectionBootstrapError("checkpoint is malformed")
        if checkpoint.get("artifact") is not None or checkpoint.get("cursor") is not None:
            # A peer may still be scanning.  Return its durable value so the
            # caller can adopt/reload it rather than regressing to a stale
            # local terminal snapshot.
            session.commit()
            session.refresh(generation)
            session.expunge(generation)
            return generation
        ready_checkpoint = {**dict(checkpoint), "phase": "verify", "artifact": None, "cursor": None}
        changed = session.execute(
            update(SettlementProjectionGeneration)
            .where(
                SettlementProjectionGeneration.generation_id == generation_id,
                SettlementProjectionGeneration.state == "staging",
            )
            .values(
                state="ready",
                checkpoint_json=ready_checkpoint,
                last_key=generation.last_key,
            )
        ).rowcount
        if changed != 1:
            session.rollback()
            _close_session(session)
            return _load_generation(session_factory, generation_id)  # type: ignore[return-value]
        session.commit()
        generation = session.get(SettlementProjectionGeneration, generation_id)
        if generation is None:
            raise LegacyProjectionBootstrapError("generation disappeared after ready transition")
        session.refresh(generation)
        session.expunge(generation)
        return generation
    except Exception:
        try:
            session.rollback()
        finally:
            _close_session(session)
        raise
    finally:
        _close_session(session)


def _ensure_null_pointer(session_factory: Callable[[], Session]) -> None:
    """Materialize the nullable pointer row after valid preflight.

    Keeping a single row lets the final publication use a portable SQL NULL
    compare-and-swap instead of racing an INSERT against another certifier.
    """

    session = _open_session(session_factory)
    try:
        session.execute(
            text(
                "INSERT INTO settlement_projection_active "
                "(projection_name, generation_id) VALUES (:projection_name, NULL) "
                "ON CONFLICT (projection_name) DO NOTHING"
            ),
            {"projection_name": PROJECTION},
        )
        session.commit()
    except Exception:
        try:
            session.rollback()
        finally:
            _close_session(session)
        raise
    _close_session(session)


def _load_generation(
    session_factory: Callable[[], Session], generation_id: str
) -> SettlementProjectionGeneration | None:
    session = _open_session(session_factory)
    try:
        row = session.get(SettlementProjectionGeneration, generation_id)
        if row is None:
            return None
        # Detach values needed after the short session closes.
        session.expunge(row)
        return row
    finally:
        _close_session(session)


def _validate_checkpoint(
    generation: SettlementProjectionGeneration,
    resource: tuple[int, int, int, int],
) -> dict[str, Any]:
    state = _as_text(generation.state)
    if state not in {"staging", "ready", "published", "failed"}:
        raise LegacyProjectionBootstrapError("generation state is invalid")
    lineage_depth = _strict_int(generation.lineage_depth, "generation lineage_depth", nonnegative=True)
    if (
        _as_text(generation.projection_name) != PROJECTION
        or generation.base_generation_id is not None
        or lineage_depth != 0
        or _as_text(generation.input_fingerprint) != _input_fingerprint()
    ):
        raise LegacyProjectionBootstrapError("generation lineage metadata is incompatible")
    rows, write_bytes, wal_bytes, headroom = resource
    persisted_rows = _strict_int(
        generation.estimated_write_rows, "generation estimated_write_rows", nonnegative=True
    )
    persisted_write_bytes = _strict_int(
        generation.estimated_write_bytes,
        "generation estimated_write_bytes",
        nonnegative=True,
    )
    persisted_wal_bytes = _strict_int(
        generation.estimated_wal_bytes, "generation estimated_wal_bytes", nonnegative=True
    )
    persisted_headroom = _strict_int(
        generation.estimated_disk_headroom_bytes,
        "generation estimated_disk_headroom_bytes",
        nonnegative=True,
    )
    if (
        persisted_rows != rows
        or persisted_write_bytes != write_bytes
        or persisted_wal_bytes != wal_bytes
        or persisted_headroom != headroom
    ):
        raise LegacyProjectionBootstrapError("checkpoint/generation resource facts changed")
    source_input = generation.source_input_json
    if not isinstance(source_input, Mapping) or _canonical_json(source_input) != _canonical_json(
        _PROTOCOL_ENVELOPE
    ):
        raise LegacyProjectionBootstrapError("generation source input envelope is incompatible")
    checkpoint = generation.checkpoint_json
    if not isinstance(checkpoint, Mapping):
        raise LegacyProjectionBootstrapError("checkpoint is malformed")
    missing_checkpoint_keys = _CHECKPOINT_REQUIRED_KEYS.difference(checkpoint)
    if missing_checkpoint_keys:
        raise LegacyProjectionBootstrapError("checkpoint required keys are missing")
    if checkpoint.get("protocol") != PROTOCOL or checkpoint.get("operation") != OPERATION:
        raise LegacyProjectionBootstrapError("checkpoint protocol is incompatible")
    phase = checkpoint.get("phase")
    if phase not in {"staging", "scan", "verify", "ready", "publish", "cleanup"}:
        raise LegacyProjectionBootstrapError("checkpoint phase is impossible")
    allowed_phases = {
        "staging": {"staging", "scan"},
        "ready": {"verify"},
        "published": {"publish"},
        "failed": {"staging", "scan", "verify", "cleanup"},
    }
    if phase not in allowed_phases[state]:
        raise LegacyProjectionBootstrapError("checkpoint phase is incompatible with generation state")
    artifact = checkpoint.get("artifact")
    if artifact is not None and artifact not in ARTIFACTS:
        raise LegacyProjectionBootstrapError("checkpoint artifact is impossible")
    cursor = checkpoint.get("cursor")
    if cursor is not None and not isinstance(cursor, Mapping):
        raise LegacyProjectionBootstrapError("checkpoint cursor is malformed")
    if phase == "cleanup":
        if artifact is not None:
            raise LegacyProjectionBootstrapError("cleanup checkpoint artifact is invalid")
        if cursor is not None:
            if set(cursor) != {"artifact", "partition_key"}:
                raise LegacyProjectionBootstrapError("cleanup checkpoint cursor is malformed")
            cleanup_artifact = cursor.get("artifact")
            cleanup_partition = cursor.get("partition_key")
            if (
                not isinstance(cleanup_artifact, str)
                or cleanup_artifact.strip() != cleanup_artifact
                or not cleanup_artifact
                or cleanup_artifact not in ARTIFACTS
                or cleanup_artifact == "None"
                or not isinstance(cleanup_partition, str)
                or cleanup_partition.strip() != cleanup_partition
                or not cleanup_partition
                or cleanup_partition == "None"
            ):
                raise LegacyProjectionBootstrapError("cleanup checkpoint cursor is invalid")
            _canonical_partition_key(cleanup_artifact, cleanup_partition)
            expected_cleanup_last_key = f"cleanup:{cleanup_artifact}:{cleanup_partition}"
            if generation.last_key != expected_cleanup_last_key:
                raise LegacyProjectionBootstrapError("cleanup checkpoint last_key is incompatible")
        elif generation.last_key is not None:
            raise LegacyProjectionBootstrapError("cleanup checkpoint last_key is incompatible")
    elif phase in {"staging", "scan"}:
        if artifact is None:
            if cursor is not None:
                raise LegacyProjectionBootstrapError("checkpoint cursor requires an artifact")
        elif cursor is not None:
            required: dict[str, tuple[str, ...]] = {
                "monthly": (
                    "month",
                    "store_id",
                    "product_scope",
                    "product_type",
                    "projection_run_id",
                    "id",
                ),
                "ranking": (
                    "period_type",
                    "period_key",
                    "store_id",
                    "product_scope",
                    "product_type",
                    "projection_run_id",
                    "id",
                ),
                "score": (
                    "snapshot_date",
                    "rule_version_id",
                    "store_id",
                    "snapshot_run_id",
                    "snapshot_id",
                ),
            }
            expected_keys = set(required[artifact])
            if set(cursor) != expected_keys:
                raise LegacyProjectionBootstrapError("checkpoint cursor is incompatible")
            for key in expected_keys:
                if cursor.get(key) is None:
                    raise LegacyProjectionBootstrapError("checkpoint cursor is incomplete")
            if artifact == "monthly":
                _month_key(cursor.get("month"), label="checkpoint month")
                for key in ("store_id", "product_scope", "product_type", "projection_run_id"):
                    _identity(cursor.get(key), label=f"checkpoint {key}")
                _strict_positive_int(cursor.get("id"), "checkpoint cursor id")
            elif artifact == "ranking":
                period_type = _strict_int(
                    cursor.get("period_type"), "checkpoint period_type"
                )
                if period_type not in {1, 2}:
                    raise LegacyProjectionBootstrapError("checkpoint period_type is invalid")
                _month_key(cursor.get("period_key"), label="checkpoint period_key")
                for key in ("store_id", "product_scope", "product_type", "projection_run_id"):
                    _identity(cursor.get(key), label=f"checkpoint {key}")
                _strict_positive_int(cursor.get("id"), "checkpoint cursor id")
            else:
                snapshot_date = cursor.get("snapshot_date")
                if isinstance(snapshot_date, str):
                    try:
                        date.fromisoformat(snapshot_date)
                    except ValueError as exc:
                        raise LegacyProjectionBootstrapError(
                            "checkpoint score date is invalid"
                        ) from exc
                elif not isinstance(snapshot_date, date):
                    raise LegacyProjectionBootstrapError("checkpoint score date is invalid")
                _identity(cursor.get("rule_version_id"), label="checkpoint rule_version_id")
                for key in ("store_id", "snapshot_run_id", "snapshot_id"):
                    _identity(cursor.get(key), label=f"checkpoint {key}")
            if generation.last_key != _cursor_token(artifact, cursor):
                raise LegacyProjectionBootstrapError(
                    "checkpoint cursor does not match generation last_key"
                )
            _canonical_partition_from_cursor(artifact, cursor)
    elif phase in {"verify", "publish"}:
        if artifact is not None or cursor is not None:
            raise LegacyProjectionBootstrapError(
                "checkpoint artifact/cursor must be NULL in terminal phase"
            )
    elif cursor is not None:
        raise LegacyProjectionBootstrapError("checkpoint cursor is not valid for this phase")
    for key in ("batch_count", "partition_count", "source_row_count"):
        value = checkpoint.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LegacyProjectionBootstrapError("checkpoint totals are inconsistent")
    batch_count = checkpoint["batch_count"]
    partition_count = checkpoint["partition_count"]
    source_row_count = checkpoint["source_row_count"]
    if source_row_count == 0:
        if batch_count != 0 or partition_count != 0:
            raise LegacyProjectionBootstrapError("checkpoint totals are inconsistent")
    elif (
        batch_count < 1
        or partition_count < 1
        or batch_count > source_row_count
        or partition_count > source_row_count
    ):
        raise LegacyProjectionBootstrapError("checkpoint totals are inconsistent")
    if phase in {"staging", "scan"} and cursor is not None and source_row_count == 0:
        raise LegacyProjectionBootstrapError("checkpoint cursor requires source rows")
    if phase in {"staging", "scan"} and cursor is None:
        if source_row_count == 0:
            if (
                batch_count != 0
                or partition_count != 0
                or generation.last_key is not None
            ):
                raise LegacyProjectionBootstrapError(
                    "initial scan checkpoint last_key or totals are inconsistent"
                )
        else:
            if batch_count <= 0 or partition_count <= 0:
                raise LegacyProjectionBootstrapError(
                    "scan transition checkpoint totals are inconsistent"
                )
            terminal_last_key = generation.last_key
            if not isinstance(terminal_last_key, str) or not terminal_last_key:
                raise LegacyProjectionBootstrapError(
                    "scan transition checkpoint last_key is invalid"
                )
            try:
                terminal_token = json.loads(
                    terminal_last_key, parse_constant=_reject_nonstandard_json_constant
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LegacyProjectionBootstrapError(
                    "scan transition checkpoint last_key is malformed"
                ) from exc
            if (
                not isinstance(terminal_token, Mapping)
                or set(terminal_token) != {"artifact", "cursor"}
                or not isinstance(terminal_token.get("artifact"), str)
                or not isinstance(terminal_token.get("cursor"), Mapping)
                or _cursor_token(
                    terminal_token["artifact"], terminal_token["cursor"]
                )
                != terminal_last_key
            ):
                raise LegacyProjectionBootstrapError(
                    "scan transition checkpoint last_key is not canonical"
                )
            terminal_artifact = terminal_token["artifact"]
            if terminal_artifact not in ARTIFACTS:
                raise LegacyProjectionBootstrapError(
                    "scan transition checkpoint last_key artifact is invalid"
                )
            _canonical_partition_from_cursor(terminal_artifact, terminal_token["cursor"])
            if artifact is not None:
                if (
                    ARTIFACTS.index(terminal_artifact) >= ARTIFACTS.index(artifact)
                ):
                    raise LegacyProjectionBootstrapError(
                        "scan transition checkpoint last_key artifact is incompatible"
                    )
    checkpoint_batch_size = _strict_positive_int(
        checkpoint.get("batch_size"), "checkpoint batch_size"
    )
    if checkpoint_batch_size > MAX_BATCH_SIZE:
        raise LegacyProjectionBootstrapError("checkpoint batch_size exceeds maximum")
    if checkpoint.get("expected_active_pointer") is not None:
        raise LegacyProjectionBootstrapError("checkpoint expected pointer is not NULL")
    rows, write_bytes, wal_bytes, headroom = resource
    if (
        checkpoint.get("estimated_manifest_rows") != rows
        or checkpoint.get("estimated_write_bytes") != write_bytes
        or checkpoint.get("estimated_wal_bytes") != wal_bytes
        or checkpoint.get("estimated_disk_headroom_bytes") != headroom
    ):
        raise LegacyProjectionBootstrapError("checkpoint resource facts changed")
    return dict(checkpoint)


def _mark_failed(
    session_factory: Callable[[], Session], generation_id: str, code: str, reason: str
) -> None:
    try:
        _update_generation(
            session_factory,
            generation_id,
            state="failed",
            failure_code=code,
            failure_reason=f"{code}: {reason}"[:1000],
        )
    except Exception:
        # The original failure remains the useful error.  A DB outage while
        # recording the bounded failure must not trigger a second mutation.
        pass


def _fetch_all_generation_manifests(
    session_factory: Callable[[], Session],
    generation_id: str,
    artifact: str,
    *,
    max_manifest_rows: int | None = None,
) -> list[dict[str, Any]]:
    if (
        max_manifest_rows is not None
        and (
            isinstance(max_manifest_rows, bool)
            or not isinstance(max_manifest_rows, int)
            or max_manifest_rows < 0
        )
    ):
        raise LegacyProjectionBootstrapError("manifest resource cap is invalid")
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        session = _open_session(session_factory)
        try:
            params: dict[str, Any] = {
                "generation_id": generation_id,
                "artifact": artifact,
                "page_limit": (
                    MAX_BATCH_SIZE
                    if max_manifest_rows is None
                    else max(1, min(MAX_BATCH_SIZE, max_manifest_rows - len(rows)))
                ),
            }
            where = "WHERE generation_id = :generation_id AND artifact = :artifact"
            if cursor is not None:
                where += " AND partition_key > :partition_cursor"
                params["partition_cursor"] = cursor
            page = [
                dict(row)
                for row in session.execute(
                    text(
                        "SELECT generation_id, artifact, partition_key, owner_state, "
                        "source_kind, data_generation_id, base_generation_id, row_count, "
                        "amount_total_cent, status_counts_json, checksum, last_key, "
                        "created_at, published_at "
                        "FROM settlement_projection_partition_manifest "
                        f"{where} ORDER BY partition_key LIMIT :page_limit"
                    ),
                    params,
                ).mappings().all()
            ]
        finally:
            _close_session(session)
        if not page:
            break
        if max_manifest_rows is not None and len(rows) + len(page) > max_manifest_rows:
            raise LegacyProjectionBootstrapError("manifest resource cap exceeded")
        rows.extend(page)
        cursor = _as_text(page[-1].get("partition_key"))
    return rows


def _manifest_checksum_value(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact": row.get("artifact"),
        "partition_key": row.get("partition_key"),
        "owner_state": row.get("owner_state"),
        "source_kind": row.get("source_kind"),
        "data_generation_id": row.get("data_generation_id"),
        "base_generation_id": row.get("base_generation_id"),
        "row_count": _strict_int(
            row.get("row_count"), "manifest row_count", nonnegative=True
        ),
        "amount_total_cent": _strict_int(
            row.get("amount_total_cent"), "manifest amount_total_cent"
        ),
        "status_counts_json": _normalize_status_counts(row.get("status_counts_json")),
        "partition_checksum": row.get("checksum"),
    }


class _ManifestChecksumAccumulator:
    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        getattr(self._digest, "update")(b'{"artifacts":')
        getattr(self._digest, "update")(_canonical_json(list(ARTIFACTS)))
        getattr(self._digest, "update")(b',"checksum_version":')
        getattr(self._digest, "update")(_canonical_json("v1"))
        getattr(self._digest, "update")(b',"manifests":[')
        self._first = True
        self._finished = False

    def add(self, row: Mapping[str, Any]) -> None:
        if self._finished:
            raise LegacyProjectionBootstrapError("manifest checksum is already final")
        if not self._first:
            getattr(self._digest, "update")(b",")
        getattr(self._digest, "update")(_canonical_json(_manifest_checksum_value(row)))
        self._first = False

    def hexdigest(self) -> str:
        if not self._finished:
            getattr(self._digest, "update")(b'],"operation":')
            getattr(self._digest, "update")(_canonical_json(OPERATION))
            getattr(self._digest, "update")(b',"partition_key_version":')
            getattr(self._digest, "update")(_canonical_json("v1"))
            getattr(self._digest, "update")(b',"projection":')
            getattr(self._digest, "update")(_canonical_json(PROJECTION))
            getattr(self._digest, "update")(b',"protocol":')
            getattr(self._digest, "update")(_canonical_json(PROTOCOL))
            getattr(self._digest, "update")(b"}")
            self._finished = True
        return self._digest.hexdigest()


def _manifest_checksum(manifests: list[Mapping[str, Any]]) -> str:
    values = sorted(
        manifests,
        key=lambda item: (str(item.get("artifact")), str(item.get("partition_key"))),
    )
    accumulator = _ManifestChecksumAccumulator()
    for row in values:
        accumulator.add(row)
    return accumulator.hexdigest()


def _validate_compaction_source_manifest_digests(
    session_factory: Callable[[], Session], lineage_rows: Sequence[Mapping[str, Any]]
) -> None:
    expected = {
        str(row["generation_id"]): str(row["manifest_checksum"])
        for row in lineage_rows
    }
    accumulators = {
        generation_id: _ManifestChecksumAccumulator() for generation_id in expected
    }
    cursor: tuple[str, str, str] | None = None
    while True:
        session = _open_session(session_factory)
        try:
            statement = (
                select(SettlementProjectionPartitionManifest)
                .where(
                    SettlementProjectionPartitionManifest.generation_id.in_(
                        tuple(expected)
                    )
                )
                .order_by(
                    SettlementProjectionPartitionManifest.generation_id,
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                )
                .limit(MAX_BATCH_SIZE)
            )
            if cursor is not None:
                statement = statement.where(
                    or_(
                        SettlementProjectionPartitionManifest.generation_id > cursor[0],
                        and_(
                            SettlementProjectionPartitionManifest.generation_id
                            == cursor[0],
                            SettlementProjectionPartitionManifest.artifact > cursor[1],
                        ),
                        and_(
                            SettlementProjectionPartitionManifest.generation_id
                            == cursor[0],
                            SettlementProjectionPartitionManifest.artifact == cursor[1],
                            SettlementProjectionPartitionManifest.partition_key
                            > cursor[2],
                        ),
                    )
                )
            page = session.scalars(statement).all()
        except Exception as exc:
            raise LegacyProjectionBootstrapError(
                "failed to validate compaction source manifests"
            ) from exc
        finally:
            _close_session(session)
        if not page:
            break
        for row in page:
            accumulators[row.generation_id].add(
                {
                    "artifact": row.artifact,
                    "partition_key": row.partition_key,
                    "owner_state": row.owner_state,
                    "source_kind": row.source_kind,
                    "data_generation_id": row.data_generation_id,
                    "base_generation_id": row.base_generation_id,
                    "row_count": row.row_count,
                    "amount_total_cent": row.amount_total_cent,
                    "status_counts_json": row.status_counts_json,
                    "checksum": row.checksum,
                }
            )
        terminal = page[-1]
        cursor = (
            terminal.generation_id,
            terminal.artifact,
            terminal.partition_key,
        )
    for generation_id, accumulator in accumulators.items():
        if accumulator.hexdigest() != expected[generation_id]:
            raise LegacyProjectionBootstrapError(
                "compaction source manifest checksum is corrupt"
            )


def _published_artifact_terminal_last_key(
    artifact: str, manifests: Sequence[Mapping[str, Any]]
) -> str | None:
    """Derive an artifact terminal cursor from validated manifest metadata.

    Manifests are fetched in partition-key order, which is not the source
    keyset order for ranking (``cumulative`` sorts before ``monthly`` as a
    string while period_type=2 is later).  Published-root validation must
    therefore compare decoded, canonical cursors using the same order key as
    source scans instead of trusting the final fetched row.
    """

    candidates: list[tuple[tuple[Any, ...], str]] = []
    for row in manifests:
        row_count = _strict_int(
            row.get("row_count"), "published root manifest row_count", nonnegative=True
        )
        last_key = row.get("last_key")
        if row_count == 0 or last_key is None:
            continue
        try:
            token = json.loads(
                str(last_key), parse_constant=_reject_nonstandard_json_constant
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LegacyProjectionBootstrapError(
                "published root manifest last_key is malformed"
            ) from exc
        if not isinstance(token, Mapping) or token.get("artifact") != artifact:
            raise LegacyProjectionBootstrapError(
                "published root manifest last_key is incompatible"
            )
        cursor = token.get("cursor")
        if not isinstance(cursor, Mapping):
            raise LegacyProjectionBootstrapError(
                "published root manifest last_key is malformed"
            )
        candidates.append((_cursor_order_key(artifact, cursor), str(last_key)))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _validate_published_root(
    session_factory: Callable[[], Session], generation: SettlementProjectionGeneration
) -> None:
    if generation.state != "published" or generation.manifest_checksum is None:
        raise LegacyProjectionBootstrapError("published root metadata is incomplete")
    resource = (
        _strict_int(generation.estimated_write_rows, "published root manifest resource cap", nonnegative=True),
        _strict_int(
            generation.estimated_write_bytes,
            "published root estimated_write_bytes",
            nonnegative=True,
        ),
        _strict_int(
            generation.estimated_wal_bytes,
            "published root estimated_wal_bytes",
            nonnegative=True,
        ),
        _strict_int(
            generation.estimated_disk_headroom_bytes,
            "published root estimated_disk_headroom_bytes",
            nonnegative=True,
        ),
    )
    checkpoint = _validate_checkpoint(generation, resource)
    batch_size = _strict_positive_int(checkpoint.get("batch_size"), "published root batch_size")
    manifests: list[dict[str, Any]] = []
    remaining_manifest_rows = resource[0]
    manifest_rows_total = 0
    manifest_partitions = 0
    expected_batch_count = 0
    terminal_last_keys: list[str] = []
    for artifact in ARTIFACTS:
        page = _fetch_all_generation_manifests(
            session_factory,
            generation.generation_id,
            artifact,
            max_manifest_rows=remaining_manifest_rows,
        )
        for row in page:
            _validate_manifest_row(row, artifact)
        manifests.extend(page)
        remaining_manifest_rows -= len(page)
        artifact_rows = sum(
            _strict_int(row.get("row_count"), "published root manifest row_count", nonnegative=True)
            for row in page
        )
        manifest_rows_total += artifact_rows
        manifest_partitions += len(page)
        expected_batch_count += (
            (artifact_rows + batch_size - 1) // batch_size if artifact_rows else 0
        )
        artifact_terminal = _published_artifact_terminal_last_key(artifact, page)
        if artifact_terminal is not None:
            terminal_last_keys.append(artifact_terminal)
    expected_write_bytes = 16_384 + (4_096 * manifest_partitions)
    expected_wal_bytes = 2 * expected_write_bytes
    if (
        resource[0] != manifest_partitions
        or resource[1] != expected_write_bytes
        or resource[2] != expected_wal_bytes
    ):
        raise LegacyProjectionBootstrapError(
            "published root resource facts are corrupt"
        )
    expected = _empty_manifest_checksum() if not manifests else _manifest_checksum(manifests)
    if expected != generation.manifest_checksum:
        raise LegacyProjectionBootstrapError("published root manifest checksum is corrupt")
    derived_last_key = terminal_last_keys[-1] if terminal_last_keys else None
    if (
        manifest_partitions != len(manifests)
        or checkpoint.get("partition_count") != manifest_partitions
        or checkpoint.get("source_row_count") != manifest_rows_total
        or checkpoint.get("batch_count") != expected_batch_count
        or generation.last_key != derived_last_key
    ):
        raise LegacyProjectionBootstrapError("published root checkpoint terminal metadata is corrupt")


def _published_resource_guard(
    generation: SettlementProjectionGeneration,
    limits: ResourceGateConfig,
) -> CertificationResult | None:
    rows = _strict_int(
        generation.estimated_write_rows,
        "published root manifest resource cap",
        nonnegative=True,
    )
    write_bytes = _strict_int(
        generation.estimated_write_bytes,
        "published root estimated_write_bytes",
        nonnegative=True,
    )
    wal_bytes = _strict_int(
        generation.estimated_wal_bytes,
        "published root estimated_wal_bytes",
        nonnegative=True,
    )
    available_headroom = limits.observed_disk_headroom_bytes - limits.min_disk_headroom_bytes
    if rows > limits.max_manifest_rows:
        return _resource_guard("manifest_rows_exceed_limit")
    if write_bytes > limits.max_estimated_write_bytes:
        return _resource_guard("estimated_write_bytes_exceed_limit")
    if wal_bytes > limits.max_estimated_wal_bytes:
        return _resource_guard("estimated_wal_bytes_exceed_limit")
    if available_headroom < write_bytes + wal_bytes:
        return _resource_guard("disk_headroom_insufficient")
    return None


def _already_published_result(
    session_factory: Callable[[], Session],
    generation: SettlementProjectionGeneration,
    limits: ResourceGateConfig,
) -> CertificationResult:
    _validate_published_root(session_factory, generation)
    guard = _published_resource_guard(generation, limits)
    if guard is not None:
        return guard
    checkpoint = generation.checkpoint_json
    if not isinstance(checkpoint, Mapping):
        raise LegacyProjectionBootstrapError("published root checkpoint is corrupt")
    return CertificationResult(
        generation_id=generation.generation_id,
        status="already_published",
        published=False,
        resumed=False,
        batch_count=int(checkpoint.get("batch_count", 0)),
        partition_count=int(checkpoint.get("partition_count", 0)),
        source_row_count=int(checkpoint.get("source_row_count", 0)),
        last_key=generation.last_key,
        manifest_checksum=generation.manifest_checksum,
        failure_code=None,
    )


def _cleanup_failed_generation(
    session_factory: Callable[[], Session],
    generation: SettlementProjectionGeneration,
    batch_size: int,
    resource: tuple[int, int, int, int],
) -> SettlementProjectionGeneration:
    generation_id = generation.generation_id
    while True:
        session = _open_session(session_factory)
        try:
            dialect_name = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
            if dialect_name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            generation_statement = select(SettlementProjectionGeneration).where(
                SettlementProjectionGeneration.generation_id == generation_id
            )
            if dialect_name == "postgresql":
                generation_statement = generation_statement.with_for_update()
            fresh_generation = session.execute(generation_statement).scalar_one_or_none()
            if fresh_generation is None:
                raise LegacyProjectionBootstrapError("failed generation disappeared")
            if fresh_generation.state != "failed":
                session.expunge(fresh_generation)
                session.commit()
                return fresh_generation

            persisted_resource = (
                _strict_int(
                    fresh_generation.estimated_write_rows,
                    "generation estimated_write_rows",
                    nonnegative=True,
                ),
                _strict_int(
                    fresh_generation.estimated_write_bytes,
                    "generation estimated_write_bytes",
                    nonnegative=True,
                ),
                _strict_int(
                    fresh_generation.estimated_wal_bytes,
                    "generation estimated_wal_bytes",
                    nonnegative=True,
                ),
                _strict_int(
                    fresh_generation.estimated_disk_headroom_bytes,
                    "generation estimated_disk_headroom_bytes",
                    nonnegative=True,
                ),
            )
            checkpoint = _validate_checkpoint(fresh_generation, persisted_resource)
            cursor = checkpoint.get("cursor") if checkpoint.get("phase") == "cleanup" else None
            stats = _ScanStats(
                batch_count=checkpoint["batch_count"],
                partition_count=checkpoint["partition_count"],
                source_row_count=checkpoint["source_row_count"],
            )
            params: dict[str, Any] = {
                "generation_id": generation_id,
                "page_limit": batch_size,
            }
            where = "WHERE generation_id = :generation_id"
            if cursor is not None:
                if isinstance(cursor, Mapping):
                    artifact = str(cursor.get("artifact"))
                    partition = str(cursor.get("partition_key"))
                else:
                    artifact, partition = str(cursor[0]), str(cursor[1])
                where += (
                    " AND (artifact > :cleanup_artifact OR "
                    "(artifact = :cleanup_artifact AND partition_key > :cleanup_partition))"
                )
                params["cleanup_artifact"] = artifact
                params["cleanup_partition"] = partition
            page = [
                tuple(row)
                for row in session.execute(
                    text(
                        "SELECT artifact, partition_key "
                        "FROM settlement_projection_partition_manifest "
                        f"{where} ORDER BY artifact, partition_key LIMIT :page_limit"
                    ),
                    params,
                ).all()
            ]
            if not page:
                reset = session.execute(
                    update(SettlementProjectionGeneration)
                    .where(
                        SettlementProjectionGeneration.generation_id == generation_id,
                        SettlementProjectionGeneration.state == "failed",
                    )
                    .values(
                        state="staging",
                        estimated_write_rows=resource[0],
                        estimated_write_bytes=resource[1],
                        estimated_wal_bytes=resource[2],
                        estimated_disk_headroom_bytes=resource[3],
                        checkpoint_json=_checkpoint(
                            phase="staging",
                            artifact="monthly",
                            cursor=None,
                            stats=_ScanStats(),
                            resource=resource,
                            batch_size=batch_size,
                        ),
                        last_key=None,
                        manifest_checksum=None,
                        failure_code=None,
                        failure_reason=None,
                        failed_at=None,
                    )
                )
                if reset.rowcount != 1:
                    session.rollback()
                    continue
                session.commit()
                return _load_generation(session_factory, generation_id)
            for artifact, partition_key in page:
                session.execute(
                    text(
                        "DELETE FROM settlement_projection_partition_manifest "
                        "WHERE generation_id = :generation_id AND artifact = :artifact "
                        "AND partition_key = :partition_key"
                    ),
                    {
                        "generation_id": generation.generation_id,
                        "artifact": artifact,
                        "partition_key": partition_key,
                    },
                )
            cursor = (str(page[-1][0]), str(page[-1][1]))
            checkpoint_update = session.execute(
                update(SettlementProjectionGeneration)
                .where(
                    SettlementProjectionGeneration.generation_id == generation_id,
                    SettlementProjectionGeneration.state == "failed",
                )
                .values(
                    estimated_write_rows=resource[0],
                    estimated_write_bytes=resource[1],
                    estimated_wal_bytes=resource[2],
                    estimated_disk_headroom_bytes=resource[3],
                    checkpoint_json={
                        **_checkpoint(
                            phase="cleanup",
                            artifact=None,
                            cursor={"artifact": cursor[0], "partition_key": cursor[1]},
                            stats=stats,
                            resource=resource,
                            batch_size=batch_size,
                        ),
                        "cleanup_cursor": list(cursor),
                    },
                    last_key=f"cleanup:{cursor[0]}:{cursor[1]}",
                )
            )
            if checkpoint_update.rowcount != 1:
                session.rollback()
                continue
            session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            raise
        finally:
            _close_session(session)


def _scan_artifact(
    session_factory: Callable[[], Session],
    generation_id: str,
    artifact: str,
    batch_size: int,
    checkpoint: Mapping[str, Any],
    resource: tuple[int, int, int, int],
) -> tuple[dict[str, Any], _ScanStats]:
    cursor = checkpoint.get("cursor") if checkpoint.get("artifact") == artifact else None
    stats = _ScanStats(
        batch_count=int(checkpoint.get("batch_count", 0)),
        partition_count=int(checkpoint.get("partition_count", 0)),
        source_row_count=int(checkpoint.get("source_row_count", 0)),
    )
    expected_last_key: str | None = None
    known_partitions: set[str] = set()
    active_accumulators: dict[str, _PartitionAccumulator] = {}
    validated_prefix_cursor: str | None = None

    def reload_after_cas_failure() -> None:
        nonlocal cursor, expected_last_key, stats, validated_prefix_cursor
        latest_generation = _load_generation(session_factory, generation_id)
        if latest_generation is None:
            raise LegacyProjectionBootstrapError("staging generation disappeared after checkpoint CAS")
        latest_checkpoint = _validate_checkpoint(latest_generation, resource)
        cursor = (
            latest_checkpoint.get("cursor")
            if latest_generation.state == "staging"
            and latest_checkpoint.get("artifact") == artifact
            else None
        )
        expected_last_key = _as_text(latest_generation.last_key)
        stats = _ScanStats(
            batch_count=latest_checkpoint["batch_count"],
            partition_count=latest_checkpoint["partition_count"],
            source_row_count=latest_checkpoint["source_row_count"],
            last_key=expected_last_key,
        )
        known_partitions.clear()
        active_accumulators.clear()
        validated_prefix_cursor = None

    def adopt_peer_after_prefix_error(exc: LegacyProjectionBootstrapError) -> None:
        """Retry only when a peer durably advanced the shared checkpoint.

        ``source prefix has no certified manifest`` is the one semantic marker
        produced when a stale verifier observes a peer's manifest/checkpoint
        interleave.  An unchanged durable tuple remains corruption and is
        re-raised; a changed tuple is adopted and retried from a fresh page.
        """

        nonlocal cursor, expected_last_key, stats, validated_prefix_cursor
        if "source prefix has no certified manifest" not in str(exc).lower():
            raise exc
        latest_generation = _load_generation(session_factory, generation_id)
        if latest_generation is None:
            raise exc
        latest_checkpoint = _validate_checkpoint(latest_generation, resource)
        latest_artifact = latest_checkpoint.get("artifact")
        latest_cursor = (
            latest_checkpoint.get("cursor")
            if latest_artifact == artifact
            else None
        )
        latest_last_key = _as_text(latest_generation.last_key)
        if (
            _as_text(latest_generation.state) == "staging"
            and latest_artifact == artifact
            and latest_cursor == cursor
            and latest_last_key == expected_last_key
        ):
            raise exc
        cursor = latest_cursor
        expected_last_key = latest_last_key
        stats = _ScanStats(
            batch_count=latest_checkpoint["batch_count"],
            partition_count=latest_checkpoint["partition_count"],
            source_row_count=latest_checkpoint["source_row_count"],
            last_key=latest_last_key,
        )
        known_partitions.clear()
        active_accumulators.clear()
        validated_prefix_cursor = None
        raise _RetryScanPage

    while True:
        session = _open_session(session_factory)
        try:
            progress_generation = session.execute(
                select(SettlementProjectionGeneration).where(
                    SettlementProjectionGeneration.generation_id == generation_id
                )
            ).scalar_one_or_none()
            if progress_generation is None:
                raise LegacyProjectionBootstrapError("staging generation disappeared")
            remote_state = _as_text(progress_generation.state)
            remote_checkpoint = _validate_checkpoint(progress_generation, resource)
            remote_last_key = _as_text(progress_generation.last_key)
            if remote_state != "staging":
                # Another certifier may have completed the deterministic
                # generation while this invocation was between pages.  Let
                # the caller re-read the durable state rather than writing a
                # stale checkpoint.
                remote_stats = _ScanStats(
                    batch_count=remote_checkpoint["batch_count"],
                    partition_count=remote_checkpoint["partition_count"],
                    source_row_count=remote_checkpoint["source_row_count"],
                    last_key=remote_last_key,
                )
                _close_session(session)
                return remote_checkpoint, remote_stats
            remote_artifact = remote_checkpoint.get("artifact")
            if remote_artifact is None:
                remote_stats = _ScanStats(
                    batch_count=remote_checkpoint["batch_count"],
                    partition_count=remote_checkpoint["partition_count"],
                    source_row_count=remote_checkpoint["source_row_count"],
                    last_key=remote_last_key,
                )
                _close_session(session)
                return remote_checkpoint, remote_stats
            if remote_artifact != artifact:
                # A peer has either advanced to another artifact or reset the
                # durable cursor.  Return its checkpoint; the outer loop will
                # choose the current artifact and continue from there.
                remote_stats = _ScanStats(
                    batch_count=remote_checkpoint["batch_count"],
                    partition_count=remote_checkpoint["partition_count"],
                    source_row_count=remote_checkpoint["source_row_count"],
                    last_key=remote_last_key,
                )
                _close_session(session)
                return remote_checkpoint, remote_stats
            remote_cursor = remote_checkpoint.get("cursor")
            if remote_cursor != cursor or remote_last_key != expected_last_key:
                cursor = remote_cursor
                expected_last_key = remote_last_key
                stats = _ScanStats(
                    batch_count=remote_checkpoint["batch_count"],
                    partition_count=remote_checkpoint["partition_count"],
                    source_row_count=remote_checkpoint["source_row_count"],
                    last_key=remote_last_key,
                )
                known_partitions.clear()
                active_accumulators.clear()
            if cursor is not None:
                cursor_token = _cursor_token(artifact, cursor)
                if cursor_token != validated_prefix_cursor:
                    try:
                        _validate_existing_manifests_prefix_once(
                            session_factory,
                            generation_id,
                            artifact,
                            batch_size,
                            cursor,
                            resource[0],
                        )
                    except LegacyProjectionBootstrapError as exc:
                        adopt_peer_after_prefix_error(exc)
                    validated_prefix_cursor = cursor_token
            page = _select_source_page(session, artifact, batch_size, cursor)
            if not page:
                # Persist artifact transition even for an empty artifact so a
                # crash cannot re-scan a completed phase indefinitely.
                if artifact == ARTIFACTS[-1] and stats.partition_count != resource[0]:
                    raise LegacyProjectionBootstrapError(
                        "resource partition count drifted before terminal transition"
                    )
                next_artifact = (
                    ARTIFACTS[ARTIFACTS.index(artifact) + 1]
                    if artifact != ARTIFACTS[-1]
                    else None
                )
                next_checkpoint = _checkpoint(
                    phase="scan",
                    artifact=next_artifact,
                    cursor=None,
                    stats=stats,
                    resource=resource,
                    batch_size=batch_size,
                )
                statement = update(SettlementProjectionGeneration).where(
                    SettlementProjectionGeneration.generation_id == generation_id,
                    SettlementProjectionGeneration.state == "staging",
                    # The durable JSON checkpoint is part of the CAS.  A
                    # peer may legitimately retain the same last_key while
                    # advancing batch/partition totals; comparing only the
                    # cursor would let a stale page regress those facts.
                    SettlementProjectionGeneration.checkpoint_json
                    == remote_checkpoint,
                )
                if expected_last_key is None:
                    statement = statement.where(SettlementProjectionGeneration.last_key.is_(None))
                else:
                    statement = statement.where(
                        SettlementProjectionGeneration.last_key == expected_last_key
                    )
                changed = session.execute(
                    statement.values(checkpoint_json=next_checkpoint, last_key=stats.last_key)
                ).rowcount
                if changed != 1:
                    session.rollback()
                    _close_session(session)
                    reload_after_cas_failure()
                    continue
                session.commit()
                active_accumulators.clear()
                return next_checkpoint, stats

            page_keys = []
            for raw in page:
                if artifact == "monthly":
                    key = _monthly_partition(raw)
                elif artifact == "ranking":
                    key = _ranking_partition(raw)
                else:
                    key = _score_partition(raw)
                if key not in page_keys:
                    page_keys.append(key)
            existing = _load_manifests_for_keys(session, generation_id, artifact, page_keys)
            accumulators: dict[str, _PartitionAccumulator] = {
                key: active_accumulators[key]
                for key in page_keys
                if key in active_accumulators
            }
            payloads: list[dict[str, Any]] = []
            for raw in page:
                if artifact == "monthly":
                    partition_key = _monthly_partition(raw)
                    columns = _source_columns(AggStoreMonthlySettlement)
                    envelope = _row_mapping(raw, columns)
                    amount = int(raw.get("promotion_net_fee_cent") or 0) - int(
                        raw.get("management_net_fee_cent") or 0
                    )
                    status = str(_strict_int(raw.get("statement_status"), "monthly statement_status"))
                elif artifact == "ranking":
                    partition_key = _ranking_partition(raw)
                    columns = _source_columns(AggStoreRanking)
                    envelope = _row_mapping(raw, columns)
                    amount = int(raw.get("net_settlement_reference_cent") or 0)
                    status = None
                else:
                    partition_key = _score_partition(raw)
                    columns = _source_columns(StoreScoreSnapshot)
                    envelope = _row_mapping(raw, columns)
                    amount = 0
                    status = None
                accumulator = accumulators.get(partition_key)
                if accumulator is None:
                    if partition_key in existing:
                        existing_last_key = _as_text(existing[partition_key].get("last_key"))
                        expected_manifest_last_key = (
                            _cursor_token(artifact, cursor) if cursor is not None else None
                        )
                        if cursor is None and expected_last_key is None:
                            # A peer may have committed the first page after
                            # this session read the durable checkpoint but
                            # before its manifest became visible here.  This
                            # connection may still hold a stale SQLite read
                            # snapshot, so close it before refreshing the
                            # durable checkpoint in a new short session.  A
                            # true pre-cursor manifest still fails closed below.
                            session.rollback()
                            _close_session(session)
                            latest_generation = _load_generation(
                                session_factory, generation_id
                            )
                            latest_checkpoint = (
                                _validate_checkpoint(latest_generation, resource)
                                if latest_generation is not None
                                else None
                            )
                            latest_artifact = (
                                latest_checkpoint.get("artifact")
                                if isinstance(latest_checkpoint, Mapping)
                                else None
                            )
                            if (
                                latest_generation is not None
                                and (
                                    _as_text(latest_generation.state) != "staging"
                                    or latest_artifact != artifact
                                )
                            ):
                                remote_stats = _ScanStats(
                                    batch_count=latest_checkpoint["batch_count"],
                                    partition_count=latest_checkpoint["partition_count"],
                                    source_row_count=latest_checkpoint["source_row_count"],
                                    last_key=_as_text(latest_generation.last_key),
                                )
                                return (
                                    latest_checkpoint,
                                    remote_stats,
                                )
                            latest_cursor = (
                                latest_checkpoint.get("cursor")
                                if latest_checkpoint is not None
                                and latest_checkpoint.get("artifact") == artifact
                                else None
                            )
                            if latest_cursor is not None:
                                cursor = latest_cursor
                                expected_last_key = _as_text(latest_generation.last_key)
                                stats = _ScanStats(
                                    batch_count=latest_checkpoint["batch_count"],
                                    partition_count=latest_checkpoint["partition_count"],
                                    source_row_count=latest_checkpoint["source_row_count"],
                                    last_key=expected_last_key,
                                )
                                raise _RetryScanPage
                        if existing_last_key != expected_manifest_last_key:
                            # A concurrent certifier can make a manifest
                            # visible together with a newer durable cursor
                            # while this session still sees the older
                            # checkpoint snapshot.  Refresh in a new session
                            # before declaring an incompatible manifest.
                            session.rollback()
                            _close_session(session)
                            latest_generation = _load_generation(
                                session_factory, generation_id
                            )
                            latest_checkpoint = (
                                _validate_checkpoint(latest_generation, resource)
                                if latest_generation is not None
                                else None
                            )
                            latest_artifact = (
                                latest_checkpoint.get("artifact")
                                if isinstance(latest_checkpoint, Mapping)
                                else None
                            )
                            if (
                                latest_generation is not None
                                and (
                                    _as_text(latest_generation.state) != "staging"
                                    or latest_artifact != artifact
                                )
                            ):
                                remote_stats = _ScanStats(
                                    batch_count=latest_checkpoint["batch_count"],
                                    partition_count=latest_checkpoint["partition_count"],
                                    source_row_count=latest_checkpoint["source_row_count"],
                                    last_key=_as_text(latest_generation.last_key),
                                )
                                return (
                                    latest_checkpoint,
                                    remote_stats,
                                )
                            latest_cursor = (
                                latest_checkpoint.get("cursor")
                                if latest_checkpoint is not None
                                and latest_checkpoint.get("artifact") == artifact
                                else None
                            )
                            latest_last_key = (
                                _as_text(latest_generation.last_key)
                                if latest_generation is not None
                                else None
                            )
                            if (
                                latest_cursor != cursor
                                or latest_last_key != expected_last_key
                            ):
                                cursor = latest_cursor
                                expected_last_key = latest_last_key
                                stats = _ScanStats(
                                    batch_count=latest_checkpoint["batch_count"],
                                    partition_count=latest_checkpoint["partition_count"],
                                    source_row_count=latest_checkpoint["source_row_count"],
                                    last_key=expected_last_key,
                                )
                                raise _RetryScanPage
                            raise LegacyProjectionBootstrapError(
                                "existing manifest conflicts with checkpoint cursor"
                            )
                        if validated_prefix_cursor is None:
                            _validate_existing_manifest_prefix(
                                session_factory, artifact, existing[partition_key], batch_size
                            )
                        accumulator = _PartitionAccumulator.from_manifest(
                            artifact, partition_key, existing[partition_key]
                        )
                        if cursor is None:
                            raise LegacyProjectionBootstrapError(
                                "manifest exists before a durable scan cursor"
                            )
                    else:
                        accumulator = _PartitionAccumulator.fresh(artifact, partition_key)
                        if partition_key not in known_partitions:
                            stats.partition_count += 1
                            known_partitions.add(partition_key)
                    accumulators[partition_key] = accumulator
                accumulator.add(envelope, amount=amount, status=status)
                row_cursor = _cursor_from_row(artifact, raw)
                accumulator.last_key = _cursor_token(artifact, row_cursor)
                stats.last_key = accumulator.last_key
                payloads = [
                    _manifest_payload(
                        generation_id,
                        artifact,
                        key,
                        item.manifest_values(),
                    )
                    for key, item in accumulators.items()
                ]

            if stats.partition_count > resource[0]:
                raise LegacyProjectionBootstrapError(
                    "resource partition count exceeded preflight estimate"
                )
            stats.batch_count += 1
            stats.source_row_count += len(page)
            last_cursor = _cursor_from_row(artifact, page[-1])
            next_checkpoint = _checkpoint(
                phase="scan",
                artifact=artifact,
                cursor=last_cursor,
                stats=stats,
                resource=resource,
                batch_size=batch_size,
            )
            _upsert_manifests(session, payloads)
            statement = update(SettlementProjectionGeneration).where(
                SettlementProjectionGeneration.generation_id == generation_id,
                SettlementProjectionGeneration.state == "staging",
                SettlementProjectionGeneration.checkpoint_json == remote_checkpoint,
            )
            if expected_last_key is None:
                statement = statement.where(SettlementProjectionGeneration.last_key.is_(None))
            else:
                statement = statement.where(
                    SettlementProjectionGeneration.last_key == expected_last_key
                )
            changed = session.execute(
                statement.values(checkpoint_json=next_checkpoint, last_key=stats.last_key)
            ).rowcount
            if changed != 1:
                session.rollback()
                _close_session(session)
                reload_after_cas_failure()
                continue
            session.commit()
            cursor = last_cursor
            expected_last_key = stats.last_key
            validated_prefix_cursor = _cursor_token(artifact, cursor)
            last_partition_key = (
                _monthly_partition(page[-1])
                if artifact == "monthly"
                else _ranking_partition(page[-1])
                if artifact == "ranking"
                else _score_partition(page[-1])
            )
            active_accumulators = {
                last_partition_key: accumulators[last_partition_key]
            }
        except _RetryScanPage:
            try:
                session.rollback()
            finally:
                _close_session(session)
            continue
        except (LegacyProjectionBootstrapError, IntegrityError) as exc:
            try:
                session.rollback()
            finally:
                _close_session(session)
            if isinstance(exc, IntegrityError):
                raise LegacyProjectionBootstrapError("manifest write conflict")
            raise
        except Exception:
            try:
                session.rollback()
            finally:
                _close_session(session)
            raise
        _close_session(session)


def _verify_artifact(
    session_factory: Callable[[], Session],
    generation_id: str,
    artifact: str,
    batch_size: int,
    *,
    max_manifest_rows: int | None = None,
) -> tuple[int, int, str | None, int]:
    if max_manifest_rows is None:
        generation = _load_generation(session_factory, generation_id)
        if generation is not None:
            max_manifest_rows = _strict_int(
                generation.estimated_write_rows,
                "manifest resource cap",
                nonnegative=True,
            )
    expected_rows = _fetch_all_generation_manifests(
        session_factory,
        generation_id,
        artifact,
        max_manifest_rows=max_manifest_rows,
    )
    expected: dict[str, Mapping[str, Any]] = {}
    for row in expected_rows:
        partition_key, _status_counts = _validate_manifest_row(row, artifact)
        if partition_key in expected:
            raise LegacyProjectionBootstrapError("duplicate or malformed partition manifest")
        expected[partition_key] = row
    seen: set[str] = set()
    cursor: Mapping[str, Any] | None = None
    row_count_total = 0
    partition_count = 0
    terminal_last_key: str | None = None
    accumulators: dict[str, _PartitionAccumulator] = {}
    while True:
        session = _open_session(session_factory)
        try:
            page = _select_source_page(session, artifact, batch_size, cursor)
        finally:
            _close_session(session)
        if not page:
            break
        for raw in page:
            if artifact == "monthly":
                key = _monthly_partition(raw)
                envelope = _row_mapping(raw, _source_columns(AggStoreMonthlySettlement))
                amount = int(raw.get("promotion_net_fee_cent") or 0) - int(
                    raw.get("management_net_fee_cent") or 0
                )
                status = str(_strict_int(raw.get("statement_status"), "monthly statement_status"))
            elif artifact == "ranking":
                key = _ranking_partition(raw)
                envelope = _row_mapping(raw, _source_columns(AggStoreRanking))
                amount = int(raw.get("net_settlement_reference_cent") or 0)
                status = None
            else:
                key = _score_partition(raw)
                envelope = _row_mapping(raw, _source_columns(StoreScoreSnapshot))
                amount = 0
                status = None
            acc = accumulators.get(key)
            if acc is None:
                acc = _PartitionAccumulator.fresh(artifact, key)
                accumulators[key] = acc
                if key not in expected:
                    raise LegacyProjectionBootstrapError(
                        "source partition has no certified manifest"
                    )
                partition_count += 1
            acc.add(envelope, amount=amount, status=status)
            terminal_last_key = _cursor_token(artifact, _cursor_from_row(artifact, raw))
            acc.last_key = terminal_last_key
            row_count_total += 1
            seen.add(key)
        cursor = _cursor_from_row(artifact, page[-1])
    if set(expected) != seen:
        raise LegacyProjectionBootstrapError("certified manifest/source partition set drifted")
    for key, manifest in expected.items():
        acc = accumulators[key]
        expected_status = _normalize_status_counts(manifest.get("status_counts_json"))
        expected_checksum = manifest.get("checksum")
        if (
            int(manifest.get("row_count") or 0) != acc.row_count
            or int(manifest.get("amount_total_cent") or 0) != acc.amount_total_cent
            or dict(expected_status) != dict(acc.status_counts)
            or expected_checksum != acc.digest
            or manifest.get("last_key") != acc.last_key
        ):
            raise LegacyProjectionBootstrapError(
                f"source drift detected for {artifact}:{key}"
            )
    expected_batch_count = (
        (row_count_total + batch_size - 1) // batch_size if row_count_total else 0
    )
    return row_count_total, partition_count, terminal_last_key, expected_batch_count


def _cleanup_different_winner_loser(
    session_factory: Callable[[], Session], generation_id: str
) -> None:
    """Delete an unpublished deterministic loser after a different winner wins.

    The active pointer is locked first, then the deterministic generation row,
    matching the publication lock order.  Only the loser generation and its
    bounded manifest rows are touched; a published winner (or a published
    deterministic generation) is never deleted.
    """

    session = _open_session(session_factory)
    try:
        dialect_name = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
        if dialect_name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        pointer_statement = text(
            "SELECT generation_id FROM settlement_projection_active "
            "WHERE projection_name = :projection_name"
            + (" FOR UPDATE" if dialect_name == "postgresql" else "")
        )
        winner_id = session.execute(
            pointer_statement, {"projection_name": PROJECTION}
        ).scalar_one_or_none()
        if winner_id is None or _as_text(winner_id) == generation_id:
            session.commit()
            return
        winner = session.get(SettlementProjectionGeneration, _as_text(winner_id))
        if winner is None or _as_text(winner.state) != "published":
            raise LegacyProjectionBootstrapError(
                "different winner cleanup requires a published active generation"
            )
        loser_statement = select(SettlementProjectionGeneration).where(
            SettlementProjectionGeneration.generation_id == generation_id
        )
        if dialect_name == "postgresql":
            loser_statement = loser_statement.with_for_update()
        loser = session.execute(loser_statement).scalar_one_or_none()
        if loser is None:
            session.commit()
            return
        loser_state = _as_text(loser.state)
        if loser_state == "published":
            session.commit()
            return
        if loser_state not in {"staging", "ready", "failed"}:
            raise LegacyProjectionBootstrapError(
                "different winner cleanup found an incompatible loser state"
            )
        manifest_cap = _strict_int(
            loser.estimated_write_rows,
            "loser manifest resource cap",
            nonnegative=True,
        )
        manifest_count = int(
            session.scalar(
                select(func.count())
                .select_from(SettlementProjectionPartitionManifest)
                .where(
                    SettlementProjectionPartitionManifest.generation_id == generation_id
                )
            )
            or 0
        )
        if manifest_count > manifest_cap:
            raise LegacyProjectionBootstrapError(
                "different winner loser manifests exceed resource cap"
            )
        session.execute(
            delete(SettlementProjectionPartitionManifest).where(
                SettlementProjectionPartitionManifest.generation_id == generation_id
            )
        )
        changed = session.execute(
            delete(SettlementProjectionGeneration).where(
                SettlementProjectionGeneration.generation_id == generation_id,
                SettlementProjectionGeneration.state.in_(
                    ("staging", "ready", "failed")
                ),
            )
        ).rowcount
        if changed != 1:
            raise LegacyProjectionBootstrapError(
                "different winner loser cleanup compare-and-swap lost"
            )
        session.commit()
    except LegacyProjectionBootstrapError:
        try:
            session.rollback()
        finally:
            _close_session(session)
        raise
    except Exception as exc:
        try:
            session.rollback()
        finally:
            _close_session(session)
        raise LegacyProjectionBootstrapError(
            "different winner loser cleanup failed"
        ) from exc
    finally:
        _close_session(session)


def _fence_remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _FenceTransientError("fence deadline expired")
    return remaining


def _fence_connection(session_factory: Callable[[], Session]) -> tuple[Any, bool]:
    """Resolve the factory's Engine without borrowing its ORM transaction."""

    probe = _open_session(session_factory)
    try:
        bind = probe.get_bind()
    finally:
        _close_session(probe)
    if bind is None:
        raise LegacyProjectionBootstrapError("final fence has no database bind")
    # Engines expose ``pool``; a directly bound Connection is already the
    # physical connection that the caller supplied and must not be replaced.
    if getattr(bind, "pool", None) is not None:
        return bind.connect(), True
    return bind, False


def _generation_advisory_lock_key(generation_id: str) -> int:
    """Return a stable signed BIGINT key for a deterministic generation."""

    digest = hashlib.sha256(generation_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class _GenerationAdvisoryLock:
    """Session-level PG lock and the factory bound to its physical connection."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        connection: Any | None = None,
        owns_connection: bool = False,
        lock_key: int | None = None,
        lock_held: bool = False,
    ) -> None:
        self.session_factory = session_factory
        self.connection = connection
        self.owns_connection = owns_connection
        self.lock_key = lock_key
        self.lock_held = lock_held

    def release(self) -> None:
        """Unlock without hiding the primary certification exception."""

        connection = self.connection
        try:
            if connection is not None and self.lock_held and self.lock_key is not None:
                try:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": self.lock_key},
                    ).scalar()
                    # Session-level advisory locks survive transaction commits;
                    # this commit merely clears the unlock statement's short
                    # transaction before the connection is returned/closed.
                    connection.commit()
                except Exception:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                finally:
                    self.lock_held = False
        finally:
            if connection is not None and self.owns_connection:
                try:
                    connection.close()
                except Exception:
                    pass


def _acquire_generation_advisory_lock(
    session_factory: Callable[[], Session], generation_id: str
) -> _GenerationAdvisoryLock:
    """Acquire a bounded session-level PG lock before any certification read.

    A contender that observes ``false`` commits and closes that probe
    connection before sleeping.  Once acquired, all internal ORM factories
    bind to the same physical connection, so the session-level lock remains
    held across short scan transactions and the final fence without keeping a
    long-running transaction open.
    """

    connection: Any | None = None
    owns_connection = False
    try:
        connection, owns_connection = _fence_connection(session_factory)
        dialect_name = getattr(getattr(connection, "dialect", None), "name", "sqlite")
        if dialect_name != "postgresql":
            if owns_connection:
                try:
                    connection.close()
                except Exception:
                    pass
            return _GenerationAdvisoryLock(session_factory=session_factory)

        lock_key = _generation_advisory_lock_key(generation_id)
        deadline = time.monotonic() + _GENERATION_ADVISORY_LOCK_DEADLINE_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _FenceTransientError("generation advisory lock timeout")
            try:
                acquired = bool(
                    connection.execute(
                        text("SELECT pg_try_advisory_lock(:lock_key)"),
                        {"lock_key": lock_key},
                    ).scalar()
                )
                # Never retain a transaction while polling or scanning.
                connection.commit()
            except Exception as exc:
                try:
                    connection.rollback()
                except Exception:
                    pass
                raise _FenceTransientError(
                    "generation advisory lock acquisition failed"
                ) from exc
            if acquired:
                locked_factory = sessionmaker(
                    bind=connection,
                    autoflush=False,
                    future=True,
                )
                return _GenerationAdvisoryLock(
                    session_factory=locked_factory,
                    connection=connection,
                    owns_connection=owns_connection,
                    lock_key=lock_key,
                    lock_held=True,
                )
            # A failed try does not keep a server transaction or a pooled
            # connection open while waiting.  Reopen a fresh probe on the next
            # iteration; only the acquired connection is retained for the
            # locked certification body.
            if owns_connection and connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
                connection = None
            time.sleep(min(0.01, remaining))
            if owns_connection:
                connection, owns_connection = _fence_connection(session_factory)
    except _FenceTransientError:
        if connection is not None and owns_connection:
            try:
                connection.close()
            except Exception:
                pass
        raise
    except Exception as exc:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
            if owns_connection:
                try:
                    connection.close()
                except Exception:
                    pass
        raise _FenceTransientError(
            "generation advisory lock acquisition failed"
        ) from exc


def _refresh_fence_timeouts(
    connection: Any, deadline: float, dialect_name: str | None = None
) -> int:
    """Refresh bounded lock/statement timeouts from the monotonic deadline."""

    if dialect_name is None:
        dialect_name = getattr(getattr(connection, "dialect", None), "name", None)
    if dialect_name == "sqlite":
        timeout_ms = max(1, int(_fence_remaining(deadline) * 1000))
        connection.exec_driver_sql(f"PRAGMA busy_timeout = {timeout_ms}")
        _fence_remaining(deadline)
        return timeout_ms
    if dialect_name == "postgresql":
        lock_timeout_ms = max(1, int(_fence_remaining(deadline) * 1000))
        connection.exec_driver_sql(
            f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'"
        )
        statement_timeout_ms = max(1, int(_fence_remaining(deadline) * 1000))
        connection.exec_driver_sql(
            f"SET LOCAL statement_timeout = '{statement_timeout_ms}ms'"
        )
        return min(lock_timeout_ms, statement_timeout_ms)
    raise LegacyProjectionBootstrapError("unsupported final fence dialect")


def _begin_final_fence(connection: Any, deadline: float) -> str:
    dialect_name = getattr(getattr(connection, "dialect", None), "name", None)
    if dialect_name == "sqlite":
        _refresh_fence_timeouts(connection, deadline, dialect_name)
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        _fence_remaining(deadline)
        return dialect_name
    if dialect_name == "postgresql":
        _fence_remaining(deadline)
        connection.exec_driver_sql("BEGIN")
        _fence_remaining(deadline)
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        source_tables = [
            "agg_store_monthly_settlement",
            "agg_store_ranking",
            "store_score_snapshot_runs",
            "store_score_snapshots",
        ]
        for table_name in source_tables:
            _refresh_fence_timeouts(connection, deadline, dialect_name)
            connection.exec_driver_sql(f"LOCK TABLE {table_name} IN SHARE MODE")
            _fence_remaining(deadline)
        return dialect_name
    raise LegacyProjectionBootstrapError("unsupported final fence dialect")


def _is_transient_fence_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "database is locked",
            "database is busy",
            "lock timeout",
            "statement timeout",
            "could not obtain lock",
            "timed out",
            "timeout",
            "deadline",
        )
    )


def _finalize_generation_fenced(
    session_factory: Callable[[], Session],
    generation_id: str,
    resource: tuple[int, int, int, int],
    batch_size: int,
    resumed: bool,
) -> CertificationResult:
    """Verify and publish on one write-blocking coordinator transaction."""

    deadline = time.monotonic() + _FINAL_FENCE_DEADLINE_SECONDS
    connection: Any | None = None
    owns_connection = False
    coordinator: Session | None = None
    try:
        connection, owns_connection = _fence_connection(session_factory)
        dialect_name = _begin_final_fence(connection, deadline)
        coordinator = Session(
            bind=connection,
            autoflush=False,
            future=True,
            join_transaction_mode="rollback_only",
        )

        # Materialize and lock the active identity before any final source
        # read.  SQLite's BEGIN IMMEDIATE is the row/table write fence; PG
        # additionally uses FOR UPDATE on the active and deterministic rows.
        _refresh_fence_timeouts(connection, deadline, dialect_name)
        coordinator.execute(
            text(
                "INSERT INTO settlement_projection_active "
                "(projection_name, generation_id) VALUES (:projection_name, NULL) "
                "ON CONFLICT (projection_name) DO NOTHING"
            ),
            {"projection_name": PROJECTION},
        )
        _fence_remaining(deadline)
        _refresh_fence_timeouts(connection, deadline, dialect_name)
        pointer = coordinator.execute(
            text(
                "SELECT generation_id FROM settlement_projection_active "
                "WHERE projection_name = :projection_name"
                + (" FOR UPDATE" if dialect_name == "postgresql" else "")
            ),
            {"projection_name": PROJECTION},
        ).scalar_one_or_none()
        _fence_remaining(deadline)
        generation_statement = select(SettlementProjectionGeneration).where(
            SettlementProjectionGeneration.generation_id == generation_id
        )
        if dialect_name == "postgresql":
            generation_statement = generation_statement.with_for_update()
        _refresh_fence_timeouts(connection, deadline, dialect_name)
        target = coordinator.execute(generation_statement).scalar_one_or_none()
        _fence_remaining(deadline)
        if target is None:
            raise LegacyProjectionBootstrapError("certification generation disappeared")

        page_factory = sessionmaker(
            bind=connection,
            autoflush=False,
            future=True,
            join_transaction_mode="create_savepoint",
        )

        def fenced_page_factory() -> Session:
            _refresh_fence_timeouts(connection, deadline, dialect_name)
            return page_factory()

        pointer_text = _as_text(pointer)
        if pointer_text is not None and pointer_text != generation_id:
            raise _DifferentWinnerConflict(
                "another generation already owns settlement pointer"
            )
        if pointer_text == generation_id:
            if _as_text(target.state) != "published":
                raise LegacyProjectionBootstrapError(
                    "publication pointer is attached to a non-published generation"
                )
            _validate_published_root(fenced_page_factory, target)
            checkpoint = target.checkpoint_json
            if not isinstance(checkpoint, Mapping):
                raise LegacyProjectionBootstrapError("published root checkpoint is corrupt")
            connection.rollback()
            return CertificationResult(
                generation_id=generation_id,
                status="already_published",
                published=False,
                resumed=False,
                batch_count=int(checkpoint.get("batch_count", 0)),
                partition_count=int(checkpoint.get("partition_count", 0)),
                source_row_count=int(checkpoint.get("source_row_count", 0)),
                last_key=target.last_key,
                manifest_checksum=target.manifest_checksum,
                failure_code=None,
            )
        if _as_text(target.state) not in {"staging", "ready"}:
            raise LegacyProjectionBootstrapError("generation is not ready for final fence")

        checkpoint = _validate_checkpoint(target, resource)
        if target.state == "staging" and checkpoint.get("artifact") is not None:
            raise _FenceTransientError("generation is still staging before final fence")

        total_rows = 0
        total_partitions = 0
        expected_batch_count = 0
        terminal_last_keys: list[str] = []
        for artifact in ARTIFACTS:
            _fence_remaining(deadline)
            rows, partitions, terminal_last_key, artifact_batch_count = _verify_artifact(
                fenced_page_factory, generation_id, artifact, batch_size
            )
            total_rows += rows
            total_partitions += partitions
            expected_batch_count += artifact_batch_count
            if terminal_last_key is not None:
                terminal_last_keys.append(terminal_last_key)

        manifests: list[dict[str, Any]] = []
        remaining_manifest_rows = resource[0]
        for artifact in ARTIFACTS:
            _fence_remaining(deadline)
            page = _fetch_all_generation_manifests(
                fenced_page_factory,
                generation_id,
                artifact,
                max_manifest_rows=remaining_manifest_rows,
            )
            for row in page:
                _validate_manifest_row(row, artifact)
            manifests.extend(page)
            remaining_manifest_rows -= len(page)
        if total_partitions != resource[0] or len(manifests) != resource[0]:
            raise LegacyProjectionBootstrapError(
                "final fenced partition count does not match resource estimate"
            )
        manifest_checksum = (
            _empty_manifest_checksum() if not manifests else _manifest_checksum(manifests)
        )
        if target.manifest_checksum is not None and target.manifest_checksum != manifest_checksum:
            raise LegacyProjectionBootstrapError("generation manifest checksum changed")
        if (
            int(checkpoint.get("source_row_count", 0)) != total_rows
            or int(checkpoint.get("partition_count", 0)) != total_partitions
            or int(checkpoint.get("batch_count", 0)) != expected_batch_count
        ):
            raise LegacyProjectionBootstrapError(
                "checkpoint totals do not match fenced manifests"
            )
        derived_last_key = terminal_last_keys[-1] if terminal_last_keys else None
        if target.last_key != derived_last_key:
            raise LegacyProjectionBootstrapError(
                "generation terminal last_key does not match fenced source"
            )

        final_checkpoint = {
            **checkpoint,
            "phase": "publish",
            "artifact": None,
            "cursor": None,
            "partition_count": total_partitions,
            "source_row_count": total_rows,
            "batch_count": expected_batch_count,
            "batch_size": batch_size,
        }
        _refresh_fence_timeouts(connection, deadline, dialect_name)
        coordinator.execute(
            update(SettlementProjectionGeneration)
            .where(
                SettlementProjectionGeneration.generation_id == generation_id,
                SettlementProjectionGeneration.state.in_(("staging", "ready")),
            )
            .values(
                state="ready",
                checkpoint_json=final_checkpoint,
                last_key=derived_last_key,
                manifest_checksum=manifest_checksum,
            )
        )
        _fence_remaining(deadline)
        _refresh_fence_timeouts(connection, deadline, dialect_name)
        claimed = coordinator.execute(
            text(
                "UPDATE settlement_projection_active SET generation_id = :generation_id "
                "WHERE projection_name = :projection_name AND generation_id IS NULL"
            ),
            {"projection_name": PROJECTION, "generation_id": generation_id},
        ).rowcount
        _fence_remaining(deadline)
        if claimed != 1:
            raise LegacyProjectionBootstrapError(
                "publication pointer compare-and-swap was not acquired"
            )
        _refresh_fence_timeouts(connection, deadline, dialect_name)
        changed = coordinator.execute(
            update(SettlementProjectionGeneration)
            .where(
                SettlementProjectionGeneration.generation_id == generation_id,
                SettlementProjectionGeneration.state == "ready",
            )
            .values(state="published", published_at=datetime.now(timezone.utc))
        ).rowcount
        _fence_remaining(deadline)
        if changed != 1:
            raise LegacyProjectionBootstrapError("published generation lost compare-and-swap")
        _refresh_fence_timeouts(connection, deadline, dialect_name)
        _fence_remaining(deadline)
        # The coordinator connection is the only transaction that may commit
        # final ready/checksum/pointer/published metadata.
        connection.commit()
    except LegacyProjectionBootstrapError:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        raise
    except Exception as exc:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        if _is_transient_fence_error(exc):
            raise _FenceTransientError("final fence timed out") from exc
        raise
    finally:
        if coordinator is not None:
            _close_session(coordinator)
        if connection is not None and owns_connection:
            try:
                connection.close()
            except Exception:
                pass

    generation = _load_generation(session_factory, generation_id)
    if generation is None:
        raise LegacyProjectionBootstrapError("published generation disappeared")
    checkpoint = generation.checkpoint_json
    if not isinstance(checkpoint, Mapping):
        raise LegacyProjectionBootstrapError("published generation checkpoint is corrupt")
    return CertificationResult(
        generation_id=generation_id,
        status="published",
        published=True,
        resumed=resumed,
        batch_count=int(checkpoint.get("batch_count", 0)),
        partition_count=int(checkpoint.get("partition_count", 0)),
        source_row_count=int(checkpoint.get("source_row_count", 0)),
        last_key=generation.last_key,
        manifest_checksum=generation.manifest_checksum,
        failure_code=None,
    )


def _publish(
    session_factory: Callable[[], Session],
    generation_id: str,
    manifest_checksum: str,
) -> Literal["published", "already_published"]:
    session = _open_session(session_factory)
    try:
        dialect_name = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
        if dialect_name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        pointer = session.execute(
            text(
                "SELECT generation_id FROM settlement_projection_active "
                "WHERE projection_name = :projection_name"
                + (" FOR UPDATE" if dialect_name == "postgresql" else "")
            ),
            {"projection_name": PROJECTION},
        ).scalar_one_or_none()
        target = session.get(SettlementProjectionGeneration, generation_id)
        if target is None:
            raise LegacyProjectionBootstrapError("certification generation disappeared")
        if pointer is not None and _as_text(pointer) != generation_id:
            raise _DifferentWinnerConflict("another generation already owns settlement pointer")
        if target.state == "published" and pointer == generation_id:
            session.commit()
            return "already_published"
        if target.state not in {"ready", "published"}:
            raise LegacyProjectionBootstrapError("generation is not ready for publication")
        if _as_text(target.manifest_checksum) != manifest_checksum:
            raise LegacyProjectionBootstrapError("generation manifest checksum changed")
        pointer_claimed = False
        if pointer is None:
            # The nullable pointer row is materialized during valid preflight,
            # so publication is always a portable NULL compare-and-swap.  Do
            # not race an INSERT here: a concurrent certifier may have claimed
            # the row between the initial preflight read and this transaction.
            changed = session.execute(
                text(
                    "UPDATE settlement_projection_active SET generation_id = :generation_id "
                    "WHERE projection_name = :projection_name AND generation_id IS NULL"
                ),
                {"projection_name": PROJECTION, "generation_id": generation_id},
            ).rowcount
            if changed == 1:
                pointer_claimed = True
            if changed != 1:
                pointer_after = session.execute(
                    text(
                        "SELECT generation_id FROM settlement_projection_active "
                        "WHERE projection_name = :projection_name"
                    ),
                    {"projection_name": PROJECTION},
                ).scalar_one_or_none()
                if pointer_after == generation_id:
                    pointer = generation_id
                else:
                    if pointer_after is not None:
                        raise _DifferentWinnerConflict(
                            "another generation already owns settlement pointer"
                        )
                    raise LegacyProjectionBootstrapError(
                        "another generation already owns settlement pointer"
                    )
        elif target.state == "ready":
            # A ready generation must still claim the NULL pointer in this
            # transaction.  Seeing the same generation already materialized
            # with a ready state is an impossible half-published state, not a
            # second successful publication.
            raise LegacyProjectionBootstrapError(
                "publication pointer is already attached to a ready generation"
            )
        changed_generation = session.execute(
            update(SettlementProjectionGeneration)
            .where(
                SettlementProjectionGeneration.generation_id == generation_id,
                SettlementProjectionGeneration.state == "ready",
            )
            .values(state="published", published_at=datetime.now(timezone.utc))
        ).rowcount
        if changed_generation != 1:
            pointer_after = session.execute(
                text(
                    "SELECT generation_id FROM settlement_projection_active "
                    "WHERE projection_name = :projection_name"
                ),
                {"projection_name": PROJECTION},
            ).scalar_one_or_none()
            if pointer_after == generation_id:
                session.commit()
                return "already_published"
            raise LegacyProjectionBootstrapError(
                "published generation lost compare-and-swap"
            )
        if not pointer_claimed:
            raise LegacyProjectionBootstrapError(
                "publication pointer compare-and-swap was not acquired"
            )
        session.commit()
        return "published"
    except IntegrityError as exc:
        try:
            session.rollback()
        finally:
            _close_session(session)
        # A concurrent certifier can legitimately win the same deterministic
        # root.  Re-read the externally visible pointer after the failed CAS;
        # only a different winner remains a typed conflict.
        try:
            winner = _read_active_pointer(session_factory)
        except LegacyProjectionBootstrapError:
            raise LegacyProjectionBootstrapError("publication compare-and-swap lost") from exc
        if winner == generation_id:
            return "already_published"
        if winner is not None:
            raise _DifferentWinnerConflict("another generation already owns settlement pointer") from exc
        raise LegacyProjectionBootstrapError("publication compare-and-swap lost") from exc
    except Exception:
        try:
            session.rollback()
        finally:
            _close_session(session)
        raise
    finally:
        _close_session(session)


def _certify_legacy_null_root_locked(
    session_factory: Callable[[], Session],
    *,
    batch_size: int = 400,
    resource_limits: ResourceGateConfig | None = None,
) -> CertificationResult:
    """Certify and atomically publish the deterministic legacy root."""

    guard = _validate_public_arguments(batch_size, resource_limits)
    if guard is not None:
        return _resource_guard(guard)
    assert resource_limits is not None
    generation_id = _generation_id()
    resumed = False

    # Pointer preflight is deliberately the first DB access after argument
    # validation.  A different winner is a typed conflict with zero writes.
    active_pointer = _read_active_pointer(session_factory)
    if active_pointer is not None and active_pointer != generation_id:
        # The deterministic loser may have been materialized by an earlier
        # contender before this invocation entered pointer preflight.  The
        # winner remains immutable; bounded cleanup removes only an
        # unpublished deterministic loser before returning the conflict.
        _cleanup_different_winner_loser(session_factory, generation_id)
        raise _DifferentWinnerConflict(
            "settlement active pointer identifies a different generation"
        )
    if active_pointer == generation_id:
        generation = _load_generation(session_factory, generation_id)
        if generation is None:
            raise LegacyProjectionBootstrapError(
                "active pointer target is not a valid published root"
            )
        return _already_published_result(session_factory, generation, resource_limits)

    resource = _resource_preflight(session_factory, resource_limits)
    if isinstance(resource, CertificationResult):
        return resource
    _preflight_source_integrity(session_factory, batch_size)

    try:
        generation = _load_generation(session_factory, generation_id)
        if active_pointer == generation_id:
            if generation is None:
                raise LegacyProjectionBootstrapError(
                    "active pointer target is not a valid published root"
                )
            return _already_published_result(session_factory, generation, resource_limits)

        if generation is None:
            session = _open_session(session_factory)
            try:
                session.add(
                    SettlementProjectionGeneration(
                        generation_id=generation_id,
                        base_generation_id=None,
                        generation_kind="legacy_root",
                        projection_name=PROJECTION,
                        state="staging",
                        input_fingerprint=_input_fingerprint(),
                        lineage_depth=0,
                        estimated_write_rows=resource[0],
                        estimated_write_bytes=resource[1],
                        estimated_wal_bytes=resource[2],
                        estimated_disk_headroom_bytes=resource[3],
                        checkpoint_json=_checkpoint(
                            phase="scan",
                            artifact="monthly",
                            cursor=None,
                            stats=_ScanStats(),
                            resource=resource,
                            batch_size=batch_size,
                        ),
                        last_key=None,
                        manifest_checksum=None,
                        source_input_json=dict(_PROTOCOL_ENVELOPE),
                    )
                )
                session.commit()
            except IntegrityError:
                session.rollback()
                resumed = True
            finally:
                _close_session(session)
            generation = _load_generation(session_factory, generation_id)
            if generation is None:
                raise LegacyProjectionBootstrapError("certification generation insert raced and disappeared")
        else:
            resumed = True

        if generation.input_fingerprint != _input_fingerprint() or generation.projection_name != PROJECTION:
            raise LegacyProjectionBootstrapError("deterministic generation metadata conflicts")
        if generation.state == "published":
            if active_pointer != generation_id:
                # A concurrent contender may have committed the deterministic
                # generation and pointer after this invocation's initial
                # preflight.  Re-read the pointer before treating it as a
                # corruption or conflict.
                active_pointer = _read_active_pointer(session_factory)
            if active_pointer == generation_id:
                return _already_published_result(session_factory, generation, resource_limits)
            raise LegacyProjectionBootstrapError("published certification has no active pointer")
        if generation.state == "failed":
            generation = _cleanup_failed_generation(
                session_factory, generation, batch_size, resource
            )
            checkpoint = _validate_checkpoint(generation, resource)
            resumed = True
        elif generation.state not in {"staging", "ready"}:
            raise LegacyProjectionBootstrapError("generation state is incompatible")
        else:
            checkpoint = _validate_checkpoint(generation, resource)

        # A ready generation is re-verified from source before any publication;
        # a staging generation continues the durable keyset scan.
        if generation.state == "staging":
            while True:
                # Re-read the durable state before selecting each artifact so
                # a concurrent certifier's committed checkpoint is adopted
                # instead of being regressed by a stale worker.
                generation = _load_generation(session_factory, generation_id)
                if generation is None:
                    raise LegacyProjectionBootstrapError("staging generation disappeared")
                if generation.state != "staging":
                    checkpoint = _validate_checkpoint(generation, resource)
                    break
                checkpoint = _validate_checkpoint(generation, resource)
                current_artifact = checkpoint.get("artifact")
                if current_artifact is None:
                    break
                checkpoint, stats = _scan_artifact(
                    session_factory,
                    generation_id,
                    str(current_artifact),
                    batch_size,
                    checkpoint,
                    resource,
                )
            generation = _load_generation(session_factory, generation_id)
            if generation is None:
                raise LegacyProjectionBootstrapError("staging generation disappeared")
            checkpoint = _validate_checkpoint(generation, resource)
            if generation.state == "published":
                active_after_scan = _read_active_pointer(session_factory)
                if active_after_scan == generation_id:
                    return _already_published_result(session_factory, generation, resource_limits)
                raise LegacyProjectionBootstrapError(
                    "published certification has no active pointer"
                )
            if generation.state == "staging":
                generation = _promote_staging_to_ready(session_factory, generation_id)
                if generation.state == "staging":
                    # A peer was still scanning when this verifier reached
                    # the transition fence.  Adopt its durable checkpoint
                    # and continue the keyset scan instead of publishing a
                    # stale local terminal snapshot.
                    checkpoint = _validate_checkpoint(generation, resource)
                    while generation.state == "staging" and checkpoint.get("artifact") is not None:
                        checkpoint, _ = _scan_artifact(
                            session_factory,
                            generation_id,
                            str(checkpoint["artifact"]),
                            batch_size,
                            checkpoint,
                            resource,
                        )
                        generation = _load_generation(session_factory, generation_id)
                        if generation is None:
                            raise LegacyProjectionBootstrapError(
                                "staging generation disappeared during ready adoption"
                            )
                        if generation.state != "staging":
                            break
                        checkpoint = _validate_checkpoint(generation, resource)
                    if generation.state == "staging":
                        generation = _promote_staging_to_ready(
                            session_factory, generation_id
                        )
        elif generation.state == "ready":
            checkpoint = _validate_checkpoint(generation, resource)

        return _finalize_generation_fenced(
            session_factory,
            generation_id,
            resource,
            batch_size,
            resumed,
        )
    except LegacyProjectionBootstrapError as exc:
        existing = _load_generation(session_factory, generation_id)
        conflict = isinstance(exc, _DifferentWinnerConflict)
        transient_fence = isinstance(exc, _FenceTransientError)
        if conflict and existing is not None:
            _cleanup_different_winner_loser(session_factory, generation_id)
        if (
            not conflict
            and not transient_fence
            and existing is not None
            and existing.state in {"staging", "ready"}
        ):
            _mark_failed(session_factory, generation_id, "certification_failed", str(exc))
        raise
    except Exception as exc:
        # DB/injected interruptions are intentionally left in their last
        # committed staging/ready state so a retry can resume from checkpoint.
        raise LegacyProjectionBootstrapError("legacy root certification failed") from exc


def certify_legacy_null_root(
    session_factory: Callable[[], Session],
    *,
    batch_size: int = 400,
    resource_limits: ResourceGateConfig | None = None,
) -> CertificationResult:
    """Certify the deterministic root under one bounded PG advisory lock."""

    guard = _validate_public_arguments(batch_size, resource_limits)
    if guard is not None:
        return _resource_guard(guard)
    assert resource_limits is not None
    generation_id = _generation_id()
    advisory_lock = _acquire_generation_advisory_lock(session_factory, generation_id)
    try:
        return _certify_legacy_null_root_locked(
            advisory_lock.session_factory,
            batch_size=batch_size,
            resource_limits=resource_limits,
        )
    finally:
        advisory_lock.release()


_COMPACTION_CHECKPOINT_KEYS = frozenset(
    {
        "protocol",
        "operation",
        "phase",
        "base_generation_id",
        "expected_active_pointer",
        "cursor",
        "batch_size",
        "batch_count",
        "partition_count",
        "source_generation_count",
        "effective_checksum",
        "estimated_manifest_rows",
        "estimated_write_rows",
        "estimated_write_bytes",
        "estimated_wal_bytes",
        "estimated_disk_headroom_bytes",
    }
)


def _compaction_guard(base_generation_id: str, code: str) -> CompactionResult:
    return CompactionResult(
        generation_id=None,
        status="resource_guard",
        ready=False,
        resumed=False,
        base_generation_id=base_generation_id,
        batch_count=0,
        partition_count=0,
        source_generation_count=0,
        last_key=None,
        manifest_checksum=None,
        failure_code=code,
    )


def _compaction_not_needed(base_generation_id: str) -> CompactionResult:
    return CompactionResult(
        generation_id=None,
        status="not_needed",
        ready=False,
        resumed=False,
        base_generation_id=base_generation_id,
        batch_count=0,
        partition_count=0,
        source_generation_count=0,
        last_key=None,
        manifest_checksum=None,
        failure_code=None,
    )


def _validate_compaction_arguments(
    base_generation_id: Any,
    threshold_config: Any,
    resource_limits: Any,
) -> str | None:
    if (
        not isinstance(base_generation_id, str)
        or not base_generation_id
        or base_generation_id.strip() != base_generation_id
    ):
        return "invalid_base_generation_id"
    if not isinstance(threshold_config, CompactionThresholdConfig):
        return "invalid_threshold_config"
    if (
        isinstance(threshold_config.minimum_lineage_depth, bool)
        or not isinstance(threshold_config.minimum_lineage_depth, int)
        or not 1 <= threshold_config.minimum_lineage_depth <= 64
        or isinstance(threshold_config.batch_size, bool)
        or not isinstance(threshold_config.batch_size, int)
        or not 1 <= threshold_config.batch_size <= MAX_BATCH_SIZE
    ):
        return "invalid_threshold_config"
    return _validate_public_arguments(threshold_config.batch_size, resource_limits)


def _load_compaction_lineage(
    session_factory: Callable[[], Session], base_generation_id: str
) -> list[dict[str, Any]]:
    session = _open_session(session_factory)
    try:
        pointer = session.scalar(
            select(SettlementProjectionActive.generation_id).where(
                SettlementProjectionActive.projection_name == PROJECTION
            )
        )
        if _as_text(pointer) != base_generation_id:
            raise LegacyProjectionBootstrapError(
                "compaction base is not the active settlement generation"
            )
        rows = [
            dict(row)
            for row in session.execute(
                text(
                    """
                    WITH RECURSIVE compaction_lineage AS (
                        SELECT generation_id, base_generation_id, generation_kind,
                               compaction_base_generation_id, projection_name, state,
                               lineage_depth, manifest_checksum, 0 AS hop
                        FROM settlement_projection_generation
                        WHERE generation_id = :base_generation_id
                        UNION ALL
                        SELECT generation.generation_id,
                               generation.base_generation_id,
                               generation.generation_kind,
                               generation.compaction_base_generation_id,
                               generation.projection_name, generation.state,
                               generation.lineage_depth, generation.manifest_checksum,
                               compaction_lineage.hop + 1
                        FROM settlement_projection_generation AS generation
                        JOIN compaction_lineage
                          ON generation.generation_id = compaction_lineage.base_generation_id
                        WHERE compaction_lineage.hop < 65
                    )
                    SELECT generation_id, base_generation_id, generation_kind,
                           compaction_base_generation_id, projection_name, state,
                           lineage_depth, manifest_checksum, hop
                    FROM compaction_lineage
                    ORDER BY hop
                    """
                ),
                {"base_generation_id": base_generation_id},
            ).mappings().all()
        ]
    except LegacyProjectionBootstrapError:
        raise
    except Exception as exc:
        raise LegacyProjectionBootstrapError("failed to read compaction lineage") from exc
    finally:
        _close_session(session)
    if not rows or len(rows) > 65:
        raise LegacyProjectionBootstrapError("compaction lineage is missing or too deep")
    try:
        head_depth = _strict_int(
            rows[0].get("lineage_depth"), "compaction base lineage depth", nonnegative=True
        )
    except LegacyProjectionBootstrapError:
        raise
    if head_depth != len(rows) - 1:
        raise LegacyProjectionBootstrapError("compaction lineage is incomplete")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        generation_id = _as_text(row.get("generation_id"))
        if generation_id is None or generation_id in seen:
            raise LegacyProjectionBootstrapError("compaction lineage identity is invalid")
        seen.add(generation_id)
        if _as_text(row.get("projection_name")) != PROJECTION:
            raise LegacyProjectionBootstrapError("compaction lineage projection is invalid")
        state = _as_text(row.get("state"))
        if (index == 0 and state != "published") or (
            index > 0 and state not in {"published", "superseded"}
        ):
            raise LegacyProjectionBootstrapError("compaction lineage state is invalid")
        kind = _as_text(row.get("generation_kind"))
        if kind not in {"lineage", "legacy_root", "compact"}:
            raise LegacyProjectionBootstrapError("compaction lineage kind is invalid")
        if index == 0 and kind == "compact":
            if len(rows) != 1 or row.get("base_generation_id") is not None:
                raise LegacyProjectionBootstrapError("compact base metadata is invalid")
        elif kind not in {"lineage", "legacy_root"}:
            raise LegacyProjectionBootstrapError("nested compact lineage is invalid")
        if kind != "compact" and row.get("compaction_base_generation_id") is not None:
            raise LegacyProjectionBootstrapError("ordinary compaction source is invalid")
        depth = _strict_int(
            row.get("lineage_depth"), "compaction lineage depth", nonnegative=True
        )
        if depth != head_depth - index:
            raise LegacyProjectionBootstrapError("compaction lineage depth is invalid")
        digest = row.get("manifest_checksum")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise LegacyProjectionBootstrapError("compaction source digest is invalid")
        expected_base = (
            _as_text(rows[index + 1].get("generation_id"))
            if index + 1 < len(rows)
            else None
        )
        if _as_text(row.get("base_generation_id")) != expected_base:
            raise LegacyProjectionBootstrapError("compaction lineage base link is invalid")
        if kind == "legacy_root" and (expected_base is not None or depth != 0):
            raise LegacyProjectionBootstrapError("legacy-root compaction source is invalid")
    if _as_text(rows[0].get("generation_kind")) != "compact":
        _validate_compaction_source_manifest_digests(session_factory, rows)
    return rows


def _compaction_key_page(
    session_factory: Callable[[], Session],
    lineage_ids: Sequence[str],
    cursor: tuple[str, str] | None,
    batch_size: int,
) -> list[tuple[str, str]]:
    session = _open_session(session_factory)
    try:
        statement = (
            select(
                SettlementProjectionPartitionManifest.artifact,
                SettlementProjectionPartitionManifest.partition_key,
            )
            .where(
                SettlementProjectionPartitionManifest.generation_id.in_(lineage_ids),
                SettlementProjectionPartitionManifest.artifact.in_(ARTIFACTS),
            )
            .group_by(
                SettlementProjectionPartitionManifest.artifact,
                SettlementProjectionPartitionManifest.partition_key,
            )
            .order_by(
                SettlementProjectionPartitionManifest.artifact,
                SettlementProjectionPartitionManifest.partition_key,
            )
            .limit(batch_size)
        )
        if cursor is not None:
            statement = statement.where(
                or_(
                    SettlementProjectionPartitionManifest.artifact > cursor[0],
                    and_(
                        SettlementProjectionPartitionManifest.artifact == cursor[0],
                        SettlementProjectionPartitionManifest.partition_key > cursor[1],
                    ),
                )
            )
        return [(str(row[0]), str(row[1])) for row in session.execute(statement).all()]
    except Exception as exc:
        raise LegacyProjectionBootstrapError("failed to read compaction partition page") from exc
    finally:
        _close_session(session)


def _compaction_source_payload_page(
    session_factory: Callable[[], Session],
    base_generation_id: str,
    lineage_rows: Sequence[Mapping[str, Any]],
    keys: Sequence[tuple[str, str]],
) -> list[dict[str, Any]]:
    if not keys:
        return []
    session = _open_session(session_factory)
    try:
        resolutions: dict[tuple[str, str], Any] = {}
        for artifact in ARTIFACTS:
            artifact_keys = [partition for item_artifact, partition in keys if item_artifact == artifact]
            if not artifact_keys:
                continue
            try:
                resolved = resolve_projection_partitions(
                    session,
                    artifact=artifact,
                    partition_keys=artifact_keys,
                    pinned_generation_id=base_generation_id,
                )
            except LineageError as exc:
                raise LegacyProjectionBootstrapError(
                    "compaction source resolution failed"
                ) from exc
            for partition_key, value in resolved.items():
                resolutions[(artifact, partition_key)] = value
        selected_pairs: dict[str, list[tuple[str, str]]] = {}
        for identity, resolution in resolutions.items():
            owner = _as_text(resolution.nearest_manifest_owner_generation)
            if owner is not None:
                selected_pairs.setdefault(identity[0], []).append((owner, identity[1]))
        source_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        for artifact, pairs in selected_pairs.items():
            clauses = [
                and_(
                    SettlementProjectionPartitionManifest.generation_id == owner,
                    SettlementProjectionPartitionManifest.partition_key == partition_key,
                )
                for owner, partition_key in pairs
            ]
            rows = session.execute(
                select(SettlementProjectionPartitionManifest).where(
                    SettlementProjectionPartitionManifest.artifact == artifact,
                    or_(*clauses),
                )
            ).scalars().all()
            for row in rows:
                identity = (row.generation_id, row.artifact, row.partition_key)
                if identity in source_rows:
                    raise LegacyProjectionBootstrapError(
                        "duplicate compaction source manifest"
                    )
                source_rows[identity] = {
                    column.name: getattr(row, column.name)
                    for column in SettlementProjectionPartitionManifest.__table__.columns
                }
    finally:
        _close_session(session)
    lineage_bases = {
        str(row["generation_id"]): _as_text(row.get("base_generation_id"))
        for row in lineage_rows
    }
    payloads: list[dict[str, Any]] = []
    for artifact, partition_key in keys:
        resolution = resolutions.get((artifact, partition_key))
        if resolution is None:
            raise LegacyProjectionBootstrapError("compaction resolution is incomplete")
        if resolution.source_kind == "legacy_root":
            continue
        owner = _as_text(resolution.nearest_manifest_owner_generation)
        if owner is None:
            raise LegacyProjectionBootstrapError("compaction manifest owner is missing")
        source = source_rows.get((owner, artifact, partition_key))
        if source is None:
            raise LegacyProjectionBootstrapError("compaction source manifest is missing")
        if source.get("reference_head_generation_id") is not None:
            raise LegacyProjectionBootstrapError("ordinary source has compact reference")
        if _as_text(source.get("base_generation_id")) != lineage_bases.get(owner):
            raise LegacyProjectionBootstrapError("compaction source base metadata is invalid")
        row_count = _strict_int(
            source.get("row_count"), "compaction source row_count", nonnegative=True
        )
        amount = _strict_int(source.get("amount_total_cent"), "compaction source amount")
        status_counts = _normalize_status_counts(source.get("status_counts_json"))
        owner_state = _as_text(source.get("owner_state"))
        source_kind = _as_text(source.get("source_kind"))
        data_generation_id = _as_text(source.get("data_generation_id"))
        if resolution.source_kind == "tombstone":
            if (
                owner_state != "tombstone"
                or source_kind != "tombstone"
                or data_generation_id is not None
                or row_count != 0
            ):
                raise LegacyProjectionBootstrapError("compaction tombstone is invalid")
        elif (
            owner_state != "owned"
            or source_kind != "overlay"
            or data_generation_id != _as_text(resolution.actual_data_generation_id)
            or data_generation_id not in lineage_bases
        ):
            raise LegacyProjectionBootstrapError("compaction overlay source is invalid")
        checksum = source.get("checksum")
        if source_kind == "overlay" and (
            not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
        ):
            raise LegacyProjectionBootstrapError("compaction partition checksum is invalid")
        payloads.append(
            {
                "artifact": artifact,
                "partition_key": partition_key,
                "owner_state": owner_state,
                "source_kind": source_kind,
                "data_generation_id": data_generation_id,
                "base_generation_id": None,
                "row_count": row_count,
                "amount_total_cent": amount,
                "status_counts_json": status_counts,
                "checksum": checksum,
                "last_key": source.get("last_key"),
            }
        )
    return payloads


def _compaction_manifest_value(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact": row.get("artifact"),
        "partition_key": row.get("partition_key"),
        "owner_state": row.get("owner_state"),
        "source_kind": row.get("source_kind"),
        "data_generation_id": row.get("data_generation_id"),
        "row_count": _strict_int(
            row.get("row_count"), "compaction manifest row_count", nonnegative=True
        ),
        "amount_total_cent": _strict_int(
            row.get("amount_total_cent"), "compaction manifest amount"
        ),
        "status_counts_json": _normalize_status_counts(row.get("status_counts_json")),
        "partition_checksum": row.get("checksum"),
        "last_key": row.get("last_key"),
    }


class _CompactionChecksumAccumulator:
    """Emit the canonical manifest envelope without retaining its row array."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        getattr(self._digest, "update")(b'{"manifests":[')
        self._first = True
        self._finished = False

    def add(self, row: Mapping[str, Any]) -> None:
        if self._finished:
            raise LegacyProjectionBootstrapError("compaction checksum is already final")
        if not self._first:
            getattr(self._digest, "update")(b",")
        getattr(self._digest, "update")(
            _canonical_json(_compaction_manifest_value(row))
        )
        self._first = False

    def hexdigest(self) -> str:
        if not self._finished:
            getattr(self._digest, "update")(b'],"operation":')
            getattr(self._digest, "update")(_canonical_json(COMPACTION_OPERATION))
            getattr(self._digest, "update")(b',"projection":')
            getattr(self._digest, "update")(_canonical_json(PROJECTION))
            getattr(self._digest, "update")(b',"protocol":')
            getattr(self._digest, "update")(_canonical_json(COMPACTION_PROTOCOL))
            getattr(self._digest, "update")(b"}")
            self._finished = True
        return self._digest.hexdigest()


def _compaction_manifest_checksum(manifests: Iterable[Mapping[str, Any]]) -> str:
    accumulator = _CompactionChecksumAccumulator()
    for row in manifests:
        accumulator.add(row)
    return accumulator.hexdigest()


def _iter_compaction_payload_batches(
    session_factory: Callable[[], Session],
    base_generation_id: str,
    lineage_rows: Sequence[Mapping[str, Any]],
    batch_size: int,
    *,
    start_after: tuple[str, str] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    lineage_ids = [str(row["generation_id"]) for row in lineage_rows]
    cursor = start_after
    buffer: list[dict[str, Any]] = []
    while True:
        keys = _compaction_key_page(session_factory, lineage_ids, cursor, batch_size)
        if not keys:
            break
        source_payloads = _compaction_source_payload_page(
            session_factory, base_generation_id, lineage_rows, keys
        )
        for payload in source_payloads:
            buffer.append(payload)
            if len(buffer) == batch_size:
                yield buffer
                buffer = []
        cursor = keys[-1]
    if buffer:
        yield buffer


def _summarize_compaction_plan(
    session_factory: Callable[[], Session],
    base_generation_id: str,
    lineage_rows: Sequence[Mapping[str, Any]],
    batch_size: int,
) -> _CompactionPlanSummary:
    checksum = _CompactionChecksumAccumulator()
    manifest_rows = 0
    batch_count = 0
    last_key: str | None = None
    for page in _iter_compaction_payload_batches(
        session_factory, base_generation_id, lineage_rows, batch_size
    ):
        batch_count += 1
        for row in page:
            checksum.add(row)
            manifest_rows += 1
        terminal = page[-1]
        last_key = _canonical_json(
            {
                "artifact": terminal.get("artifact"),
                "partition_key": terminal.get("partition_key"),
            }
        ).decode("utf-8")
    return _CompactionPlanSummary(
        manifest_rows=manifest_rows,
        batch_count=batch_count,
        last_key=last_key,
        effective_checksum=checksum.hexdigest(),
    )


def _compaction_resource(
    manifest_rows: int,
    closure_rows: int,
    limits: ResourceGateConfig,
) -> tuple[tuple[int, int, int, int, int], str | None]:
    write_rows = 1 + closure_rows + manifest_rows
    write_bytes = 16_384 + 4_096 * (closure_rows + manifest_rows)
    wal_bytes = 2 * write_bytes
    headroom = limits.observed_disk_headroom_bytes - limits.min_disk_headroom_bytes
    if manifest_rows > limits.max_manifest_rows:
        return (manifest_rows, write_rows, write_bytes, wal_bytes, headroom), "manifest_rows_exceed_limit"
    if write_bytes > limits.max_estimated_write_bytes:
        return (manifest_rows, write_rows, write_bytes, wal_bytes, headroom), "estimated_write_bytes_exceed_limit"
    if wal_bytes > limits.max_estimated_wal_bytes:
        return (manifest_rows, write_rows, write_bytes, wal_bytes, headroom), "estimated_wal_bytes_exceed_limit"
    if headroom < write_bytes + wal_bytes:
        return (manifest_rows, write_rows, write_bytes, wal_bytes, headroom), "disk_headroom_insufficient"
    return (manifest_rows, write_rows, write_bytes, wal_bytes, headroom), None


def _compaction_fingerprint(
    base_generation_id: str,
    base_manifest_checksum: str,
    effective_checksum: str,
) -> str:
    return _sha256(
        _canonical_json(
            {
                "protocol": COMPACTION_PROTOCOL,
                "projection": PROJECTION,
                "operation": COMPACTION_OPERATION,
                "base_generation_id": base_generation_id,
                "base_manifest_checksum": base_manifest_checksum,
                "effective_checksum": effective_checksum,
            }
        )
    )


def _compaction_checkpoint(
    *,
    phase: str,
    base_generation_id: str,
    cursor: Mapping[str, Any] | None,
    batch_size: int,
    batch_count: int,
    partition_count: int,
    source_generation_count: int,
    effective_checksum: str,
    resource: tuple[int, int, int, int, int],
) -> dict[str, Any]:
    return {
        "protocol": COMPACTION_PROTOCOL,
        "operation": COMPACTION_OPERATION,
        "phase": phase,
        "base_generation_id": base_generation_id,
        "expected_active_pointer": base_generation_id,
        "cursor": dict(cursor) if cursor is not None else None,
        "batch_size": batch_size,
        "batch_count": batch_count,
        "partition_count": partition_count,
        "source_generation_count": source_generation_count,
        "effective_checksum": effective_checksum,
        "estimated_manifest_rows": resource[0],
        "estimated_write_rows": resource[1],
        "estimated_write_bytes": resource[2],
        "estimated_wal_bytes": resource[3],
        "estimated_disk_headroom_bytes": resource[4],
    }


def _validate_compaction_checkpoint(
    generation: SettlementProjectionGeneration,
    *,
    base_generation_id: str,
    effective_checksum: str,
    resource: tuple[int, int, int, int, int],
    batch_size: int,
    source_generation_count: int,
) -> dict[str, Any]:
    checkpoint = generation.checkpoint_json
    if not isinstance(checkpoint, Mapping) or not _COMPACTION_CHECKPOINT_KEYS.issubset(checkpoint):
        raise LegacyProjectionBootstrapError("compaction checkpoint is malformed")
    if (
        checkpoint.get("protocol") != COMPACTION_PROTOCOL
        or checkpoint.get("operation") != COMPACTION_OPERATION
        or checkpoint.get("phase") not in {"scan", "ready"}
        or checkpoint.get("base_generation_id") != base_generation_id
        or checkpoint.get("expected_active_pointer") != base_generation_id
        or checkpoint.get("effective_checksum") != effective_checksum
        or checkpoint.get("batch_size") != batch_size
        or checkpoint.get("source_generation_count") != source_generation_count
        or checkpoint.get("estimated_manifest_rows") != resource[0]
        or checkpoint.get("estimated_write_rows") != resource[1]
        or checkpoint.get("estimated_write_bytes") != resource[2]
        or checkpoint.get("estimated_wal_bytes") != resource[3]
        or checkpoint.get("estimated_disk_headroom_bytes") != resource[4]
    ):
        raise LegacyProjectionBootstrapError("compaction checkpoint conflicts")
    batch_count = _strict_int(
        checkpoint.get("batch_count"), "compaction checkpoint batch_count", nonnegative=True
    )
    partition_count = _strict_int(
        checkpoint.get("partition_count"),
        "compaction checkpoint partition_count",
        nonnegative=True,
    )
    if partition_count > resource[0] or batch_count > resource[0]:
        raise LegacyProjectionBootstrapError("compaction checkpoint totals are invalid")
    cursor = checkpoint.get("cursor")
    if cursor is not None:
        if (
            not isinstance(cursor, Mapping)
            or set(cursor) != {"artifact", "partition_key", "index"}
            or cursor.get("artifact") not in ARTIFACTS
            or not isinstance(cursor.get("partition_key"), str)
            or cursor.get("partition_key", "").strip() != cursor.get("partition_key")
            or _strict_int(cursor.get("index"), "compaction checkpoint cursor index", nonnegative=True)
            != partition_count
        ):
            raise LegacyProjectionBootstrapError("compaction checkpoint cursor is invalid")
    elif partition_count != 0 and checkpoint.get("phase") == "scan":
        raise LegacyProjectionBootstrapError("compaction checkpoint cursor is missing")
    if checkpoint.get("phase") == "ready" and cursor is not None:
        raise LegacyProjectionBootstrapError("ready compaction checkpoint has a cursor")
    return dict(checkpoint)


def _upsert_compaction_manifests(
    session: Session, generation_id: str, payloads: Sequence[Mapping[str, Any]]
) -> None:
    if not payloads:
        return
    dialect_name = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    table = SettlementProjectionPartitionManifest.__table__
    rows = [
        {
            "generation_id": generation_id,
            **dict(payload),
            "reference_head_generation_id": (
                generation_id if payload.get("source_kind") == "overlay" else None
            ),
            "created_at": datetime.now(timezone.utc),
            "published_at": None,
        }
        for payload in payloads
    ]
    # Pass rows as an executemany parameter set instead of compiling one giant
    # multi-VALUES statement.  A 400-row manifest page otherwise expands to
    # thousands of SQL variables and breaks SQLite's traditional 999-bind cap.
    statement = dialect_insert(table)
    excluded = statement.excluded
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[table.c.generation_id, table.c.artifact, table.c.partition_key],
            set_={
                "owner_state": excluded.owner_state,
                "source_kind": excluded.source_kind,
                "data_generation_id": excluded.data_generation_id,
                "base_generation_id": excluded.base_generation_id,
                "reference_head_generation_id": excluded.reference_head_generation_id,
                "row_count": excluded.row_count,
                "amount_total_cent": excluded.amount_total_cent,
                "status_counts_json": excluded.status_counts_json,
                "checksum": excluded.checksum,
                "last_key": excluded.last_key,
            },
        ),
        rows,
    )


def _compaction_manifest_page(
    session_factory: Callable[[], Session],
    generation_id: str,
    cursor: tuple[str, str] | None,
    batch_size: int,
) -> list[dict[str, Any]]:
    session = _open_session(session_factory)
    try:
        statement = (
            select(SettlementProjectionPartitionManifest)
            .where(SettlementProjectionPartitionManifest.generation_id == generation_id)
            .order_by(
                SettlementProjectionPartitionManifest.artifact,
                SettlementProjectionPartitionManifest.partition_key,
            )
            .limit(batch_size)
        )
        if cursor is not None:
            statement = statement.where(
                or_(
                    SettlementProjectionPartitionManifest.artifact > cursor[0],
                    and_(
                        SettlementProjectionPartitionManifest.artifact == cursor[0],
                        SettlementProjectionPartitionManifest.partition_key > cursor[1],
                    ),
                )
            )
        return [
            {
                "artifact": row.artifact,
                "partition_key": row.partition_key,
                "owner_state": row.owner_state,
                "source_kind": row.source_kind,
                "data_generation_id": row.data_generation_id,
                "base_generation_id": row.base_generation_id,
                "row_count": row.row_count,
                "amount_total_cent": row.amount_total_cent,
                "status_counts_json": row.status_counts_json,
                "checksum": row.checksum,
                "last_key": row.last_key,
                "reference_head_generation_id": row.reference_head_generation_id,
            }
            for row in session.scalars(statement).all()
        ]
    finally:
        _close_session(session)


def _verify_compaction_ready(
    session_factory: Callable[[], Session],
    generation: SettlementProjectionGeneration,
    *,
    base_generation_id: str,
    lineage_rows: Sequence[Mapping[str, Any]],
    plan_summary: _CompactionPlanSummary,
    resource: tuple[int, int, int, int, int],
    batch_size: int,
) -> dict[str, Any]:
    checkpoint = _validate_compaction_checkpoint(
        generation,
        base_generation_id=base_generation_id,
        effective_checksum=plan_summary.effective_checksum,
        resource=resource,
        batch_size=batch_size,
        source_generation_count=len(lineage_rows),
    )
    if (
        checkpoint.get("partition_count") != plan_summary.manifest_rows
        or checkpoint.get("batch_count") != plan_summary.batch_count
        or generation.estimated_write_rows != resource[1]
        or generation.estimated_write_bytes != resource[2]
        or generation.estimated_wal_bytes != resource[3]
        or generation.estimated_disk_headroom_bytes != resource[4]
        or generation.last_key != plan_summary.last_key
    ):
        raise LegacyProjectionBootstrapError(
            "compaction checkpoint or resource terminal facts are invalid"
        )
    if generation.state == "ready":
        if (
            checkpoint.get("phase") != "ready"
            or checkpoint.get("cursor") is not None
            or generation.manifest_checksum != plan_summary.effective_checksum
        ):
            raise LegacyProjectionBootstrapError("ready compaction metadata is invalid")
    elif generation.state == "staging":
        cursor = checkpoint.get("cursor")
        if checkpoint.get("phase") != "scan" or (
            plan_summary.manifest_rows
            and (
                not isinstance(cursor, Mapping)
                or cursor.get("index") != plan_summary.manifest_rows
            )
        ):
            raise LegacyProjectionBootstrapError("staging compaction metadata is invalid")
    else:
        raise LegacyProjectionBootstrapError("compaction verification state is invalid")
    if _read_active_pointer(session_factory) != base_generation_id:
        raise LegacyProjectionBootstrapError("compaction expected active base changed")
    expected_pages = iter(
        _iter_compaction_payload_batches(
            session_factory, base_generation_id, lineage_rows, batch_size
        )
    )
    actual_cursor: tuple[str, str] | None = None
    actual_checksum = _CompactionChecksumAccumulator()
    verified_rows = 0
    while True:
        expected_page = next(expected_pages, [])
        actual_page = _compaction_manifest_page(
            session_factory,
            generation.generation_id,
            actual_cursor,
            batch_size,
        )
        expected_rows = []
        for payload in expected_page:
            expected = dict(payload)
            expected["reference_head_generation_id"] = (
                generation.generation_id if payload.get("source_kind") == "overlay" else None
            )
            expected_rows.append(expected)
        if actual_page != expected_rows:
            raise LegacyProjectionBootstrapError("compaction manifest verification failed")
        if not actual_page:
            break
        for row in actual_page:
            actual_checksum.add(row)
        verified_rows += len(actual_page)
        terminal = actual_page[-1]
        actual_cursor = (str(terminal["artifact"]), str(terminal["partition_key"]))
    if (
        verified_rows != plan_summary.manifest_rows
        or actual_checksum.hexdigest() != plan_summary.effective_checksum
    ):
        raise LegacyProjectionBootstrapError("compaction manifest verification failed")
    session = _open_session(session_factory)
    try:
        closure = {
            row.source_generation_id: row.source_digest
            for row in session.scalars(
                select(SettlementProjectionCompactionClosure).where(
                    SettlementProjectionCompactionClosure.compact_generation_id
                    == generation.generation_id
                )
            ).all()
        }
    finally:
        _close_session(session)
    expected_closure = {
        str(row["generation_id"]): str(row["manifest_checksum"]) for row in lineage_rows
    }
    if closure != expected_closure:
        raise LegacyProjectionBootstrapError("compaction closure verification failed")
    return checkpoint


def _cleanup_failed_compaction(
    session_factory: Callable[[], Session],
    generation: SettlementProjectionGeneration,
    *,
    base_generation_id: str,
    lineage_rows: Sequence[Mapping[str, Any]],
    effective_checksum: str,
    resource: tuple[int, int, int, int, int],
    batch_size: int,
    fingerprint: str,
) -> SettlementProjectionGeneration:
    """Delete only failed compact metadata under a fresh state lock."""

    while True:
        session = _open_session(session_factory)
        try:
            dialect_name = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
            if dialect_name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            statement = select(SettlementProjectionGeneration).where(
                SettlementProjectionGeneration.generation_id == generation.generation_id
            )
            if dialect_name == "postgresql":
                statement = statement.with_for_update()
            current = session.execute(statement).scalar_one_or_none()
            if current is None:
                raise LegacyProjectionBootstrapError(
                    "failed compaction generation disappeared during cleanup"
                )
            if current.state != "failed":
                session.commit()
                session.refresh(current)
                session.expunge(current)
                return current
            manifest_keys = session.execute(
                select(
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                )
                .where(
                    SettlementProjectionPartitionManifest.generation_id
                    == generation.generation_id
                )
                .order_by(
                    SettlementProjectionPartitionManifest.artifact,
                    SettlementProjectionPartitionManifest.partition_key,
                )
                .limit(batch_size)
            ).all()
            if manifest_keys:
                session.execute(
                    delete(SettlementProjectionPartitionManifest).where(
                        SettlementProjectionPartitionManifest.generation_id
                        == generation.generation_id,
                        or_(
                            *[
                                and_(
                                    SettlementProjectionPartitionManifest.artifact
                                    == artifact,
                                    SettlementProjectionPartitionManifest.partition_key
                                    == partition_key,
                                )
                                for artifact, partition_key in manifest_keys
                            ]
                        ),
                    )
                )
                current.checkpoint_json = {
                    **_compaction_checkpoint(
                        phase="cleanup",
                        base_generation_id=base_generation_id,
                        cursor=None,
                        batch_size=batch_size,
                        batch_count=0,
                        partition_count=0,
                        source_generation_count=len(lineage_rows),
                        effective_checksum=effective_checksum,
                        resource=resource,
                    ),
                    "cleanup_deleted_rows": len(manifest_keys),
                }
                session.commit()
                continue
            session.execute(
                delete(SettlementProjectionCompactionClosure).where(
                    SettlementProjectionCompactionClosure.compact_generation_id
                    == generation.generation_id
                )
            )
            session.flush()
            session.add_all(
                [
                    SettlementProjectionCompactionClosure(
                        compact_generation_id=generation.generation_id,
                        source_generation_id=str(row["generation_id"]),
                        source_digest=str(row["manifest_checksum"]),
                    )
                    for row in lineage_rows
                ]
            )
            current.state = "staging"
            current.input_fingerprint = fingerprint
            current.estimated_write_rows = resource[1]
            current.estimated_write_bytes = resource[2]
            current.estimated_wal_bytes = resource[3]
            current.estimated_disk_headroom_bytes = resource[4]
            current.checkpoint_json = _compaction_checkpoint(
                phase="scan",
                base_generation_id=base_generation_id,
                cursor=None,
                batch_size=batch_size,
                batch_count=0,
                partition_count=0,
                source_generation_count=len(lineage_rows),
                effective_checksum=effective_checksum,
                resource=resource,
            )
            current.last_key = None
            current.manifest_checksum = None
            current.failure_code = None
            current.failure_reason = None
            current.failed_at = None
            current.source_input_json = {
                "protocol": COMPACTION_PROTOCOL,
                "projection": PROJECTION,
                "operation": COMPACTION_OPERATION,
                "base_generation_id": base_generation_id,
                "effective_checksum": effective_checksum,
            }
            session.commit()
            session.refresh(current)
            session.expunge(current)
            return current
        except Exception:
            session.rollback()
            raise
        finally:
            _close_session(session)


def _fail_compaction_generation(
    session_factory: Callable[[], Session],
    generation_id: str,
    exc: Exception,
    *,
    expected_states: Sequence[str] = ("staging",),
) -> None:
    session = _open_session(session_factory)
    try:
        session.execute(
            update(SettlementProjectionGeneration)
            .where(
                SettlementProjectionGeneration.generation_id == generation_id,
                SettlementProjectionGeneration.state.in_(tuple(expected_states)),
            )
            .values(
                state="failed",
                failure_code="compaction_failed",
                failure_reason=f"compaction_failed: {exc}"[:1000],
                failed_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        _close_session(session)


def _compact_projection_metadata_locked(
    session_factory: Callable[[], Session],
    *,
    base_generation_id: str,
    threshold_config: CompactionThresholdConfig,
    resource_limits: ResourceGateConfig,
) -> CompactionResult:
    lineage_rows = _load_compaction_lineage(session_factory, base_generation_id)
    head_depth = int(lineage_rows[0]["lineage_depth"] or 0)
    if (
        _as_text(lineage_rows[0].get("generation_kind")) == "compact"
        or head_depth < threshold_config.minimum_lineage_depth
    ):
        return _compaction_not_needed(base_generation_id)
    plan_summary = _summarize_compaction_plan(
        session_factory,
        base_generation_id,
        lineage_rows,
        threshold_config.batch_size,
    )
    effective_checksum = plan_summary.effective_checksum
    resource, guard_code = _compaction_resource(
        plan_summary.manifest_rows, len(lineage_rows), resource_limits
    )
    if guard_code is not None:
        return _compaction_guard(base_generation_id, guard_code)
    base_manifest_checksum = str(lineage_rows[0]["manifest_checksum"])
    fingerprint = _compaction_fingerprint(
        base_generation_id, base_manifest_checksum, effective_checksum
    )
    generation_id = f"settlement-compact:{fingerprint}"
    generation = _load_generation(session_factory, generation_id)
    resumed = generation is not None
    if generation is None:
        session = _open_session(session_factory)
        try:
            session.add(
                SettlementProjectionGeneration(
                    generation_id=generation_id,
                    base_generation_id=None,
                    generation_kind="compact",
                    compaction_base_generation_id=base_generation_id,
                    projection_name=PROJECTION,
                    state="staging",
                    input_fingerprint=fingerprint,
                    lineage_depth=0,
                    estimated_write_rows=resource[1],
                    estimated_write_bytes=resource[2],
                    estimated_wal_bytes=resource[3],
                    estimated_disk_headroom_bytes=resource[4],
                    checkpoint_json=_compaction_checkpoint(
                        phase="scan",
                        base_generation_id=base_generation_id,
                        cursor=None,
                        batch_size=threshold_config.batch_size,
                        batch_count=0,
                        partition_count=0,
                        source_generation_count=len(lineage_rows),
                        effective_checksum=effective_checksum,
                        resource=resource,
                    ),
                    last_key=None,
                    manifest_checksum=None,
                    source_input_json={
                        "protocol": COMPACTION_PROTOCOL,
                        "projection": PROJECTION,
                        "operation": COMPACTION_OPERATION,
                        "base_generation_id": base_generation_id,
                        "effective_checksum": effective_checksum,
                    },
                )
            )
            session.flush()
            session.add_all(
                [
                    SettlementProjectionCompactionClosure(
                        compact_generation_id=generation_id,
                        source_generation_id=str(row["generation_id"]),
                        source_digest=str(row["manifest_checksum"]),
                    )
                    for row in lineage_rows
                ]
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            resumed = True
        except Exception:
            session.rollback()
            raise
        finally:
            _close_session(session)
        generation = _load_generation(session_factory, generation_id)
    if generation is None:
        raise LegacyProjectionBootstrapError("compaction generation disappeared")
    if (
        generation.input_fingerprint != fingerprint
        or generation.generation_kind != "compact"
        or generation.base_generation_id is not None
        or generation.compaction_base_generation_id != base_generation_id
        or generation.lineage_depth != 0
        or generation.projection_name != PROJECTION
    ):
        raise LegacyProjectionBootstrapError("deterministic compaction metadata conflicts")
    if generation.state == "failed":
        generation = _cleanup_failed_compaction(
            session_factory,
            generation,
            base_generation_id=base_generation_id,
            lineage_rows=lineage_rows,
            effective_checksum=effective_checksum,
            resource=resource,
            batch_size=threshold_config.batch_size,
            fingerprint=fingerprint,
        )
        resumed = True
    if generation.state not in {"staging", "ready"}:
        raise LegacyProjectionBootstrapError("compaction generation state is incompatible")
    try:
        checkpoint = _validate_compaction_checkpoint(
            generation,
            base_generation_id=base_generation_id,
            effective_checksum=effective_checksum,
            resource=resource,
            batch_size=threshold_config.batch_size,
            source_generation_count=len(lineage_rows),
        )
    except LegacyProjectionBootstrapError as exc:
        _fail_compaction_generation(
            session_factory,
            generation_id,
            exc,
            expected_states=(generation.state,),
        )
        raise
    if generation.state == "ready":
        try:
            _verify_compaction_ready(
                session_factory,
                generation,
                base_generation_id=base_generation_id,
                lineage_rows=lineage_rows,
                plan_summary=plan_summary,
                resource=resource,
                batch_size=threshold_config.batch_size,
            )
        except LegacyProjectionBootstrapError as exc:
            _fail_compaction_generation(
                session_factory,
                generation_id,
                exc,
                expected_states=("ready",),
            )
            raise
        return CompactionResult(
            generation_id=generation_id,
            status="already_ready",
            ready=True,
            resumed=True,
            base_generation_id=base_generation_id,
            batch_count=int(checkpoint["batch_count"]),
            partition_count=int(checkpoint["partition_count"]),
            source_generation_count=len(lineage_rows),
            last_key=generation.last_key,
            manifest_checksum=generation.manifest_checksum,
            failure_code=None,
        )
    peer_ready = False
    while int(checkpoint["partition_count"]) < plan_summary.manifest_rows:
        checkpoint_cursor = checkpoint.get("cursor")
        start_after = None
        if isinstance(checkpoint_cursor, Mapping):
            start_after = (
                str(checkpoint_cursor["artifact"]),
                str(checkpoint_cursor["partition_key"]),
            )
        page = next(
            _iter_compaction_payload_batches(
                session_factory,
                base_generation_id,
                lineage_rows,
                threshold_config.batch_size,
                start_after=start_after,
            ),
            None,
        )
        if page is None:
            exc = LegacyProjectionBootstrapError(
                "compaction durable cursor has no remaining manifest page"
            )
            _fail_compaction_generation(session_factory, generation_id, exc)
            raise exc
        page_start = int(checkpoint["partition_count"])
        page_end = page_start + len(page)
        last = page[-1]
        cursor = {
            "artifact": last["artifact"],
            "partition_key": last["partition_key"],
            "index": page_end,
        }
        next_checkpoint = _compaction_checkpoint(
            phase="scan",
            base_generation_id=base_generation_id,
            cursor=cursor,
            batch_size=threshold_config.batch_size,
            batch_count=int(checkpoint["batch_count"]) + 1,
            partition_count=page_end,
            source_generation_count=len(lineage_rows),
            effective_checksum=effective_checksum,
            resource=resource,
        )
        session = _open_session(session_factory)
        adopted_checkpoint: dict[str, Any] | None = None
        try:
            dialect_name = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
            if dialect_name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            statement = select(SettlementProjectionGeneration).where(
                SettlementProjectionGeneration.generation_id == generation_id
            )
            if dialect_name == "postgresql":
                statement = statement.with_for_update()
            current = session.execute(statement).scalar_one_or_none()
            if current is None:
                raise LegacyProjectionBootstrapError("compaction page lost staging ownership")
            if current.state == "ready":
                session.commit()
                peer_ready = True
            elif current.state != "staging":
                raise LegacyProjectionBootstrapError("compaction page lost staging ownership")
            else:
                current_checkpoint = _validate_compaction_checkpoint(
                    current,
                    base_generation_id=base_generation_id,
                    effective_checksum=effective_checksum,
                    resource=resource,
                    batch_size=threshold_config.batch_size,
                    source_generation_count=len(lineage_rows),
                )
                if (
                    current_checkpoint.get("partition_count")
                    != checkpoint.get("partition_count")
                    or current_checkpoint.get("batch_count")
                    != checkpoint.get("batch_count")
                    or current_checkpoint.get("cursor") != checkpoint.get("cursor")
                ):
                    adopted_checkpoint = current_checkpoint
                    session.commit()
                else:
                    active = session.scalar(
                        select(SettlementProjectionActive.generation_id).where(
                            SettlementProjectionActive.projection_name == PROJECTION
                        )
                    )
                    if _as_text(active) != base_generation_id:
                        raise LegacyProjectionBootstrapError(
                            "compaction expected active base changed"
                        )
                    _upsert_compaction_manifests(session, generation_id, page)
                    current.checkpoint_json = next_checkpoint
                    current.last_key = _canonical_json(
                        {
                            "artifact": last["artifact"],
                            "partition_key": last["partition_key"],
                        }
                    ).decode("utf-8")
                    session.commit()
                    checkpoint = next_checkpoint
        except LegacyProjectionBootstrapError as exc:
            session.rollback()
            _fail_compaction_generation(session_factory, generation_id, exc)
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            _close_session(session)
        if peer_ready:
            break
        if adopted_checkpoint is not None:
            checkpoint = adopted_checkpoint
    generation = _load_generation(session_factory, generation_id)
    if generation is None:
        raise LegacyProjectionBootstrapError("compaction generation disappeared")
    try:
        checkpoint = _verify_compaction_ready(
            session_factory,
            generation,
            base_generation_id=base_generation_id,
            lineage_rows=lineage_rows,
            plan_summary=plan_summary,
            resource=resource,
            batch_size=threshold_config.batch_size,
        )
    except LegacyProjectionBootstrapError as exc:
        _fail_compaction_generation(
            session_factory,
            generation_id,
            exc,
            expected_states=(generation.state,),
        )
        raise
    if generation.state == "ready":
        return CompactionResult(
            generation_id=generation_id,
            status="already_ready",
            ready=True,
            resumed=True,
            base_generation_id=base_generation_id,
            batch_count=int(checkpoint["batch_count"]),
            partition_count=int(checkpoint["partition_count"]),
            source_generation_count=len(lineage_rows),
            last_key=generation.last_key,
            manifest_checksum=generation.manifest_checksum,
            failure_code=None,
        )
    transition_status: Literal["ready", "already_ready"] = "ready"
    session = _open_session(session_factory)
    try:
        dialect_name = getattr(getattr(session.bind, "dialect", None), "name", "sqlite")
        if dialect_name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        statement = select(SettlementProjectionGeneration).where(
            SettlementProjectionGeneration.generation_id == generation_id
        )
        if dialect_name == "postgresql":
            statement = statement.with_for_update()
        current = session.execute(statement).scalar_one()
        current_checkpoint = _validate_compaction_checkpoint(
            current,
            base_generation_id=base_generation_id,
            effective_checksum=effective_checksum,
            resource=resource,
            batch_size=threshold_config.batch_size,
            source_generation_count=len(lineage_rows),
        )
        if current.state == "ready":
            if (
                current_checkpoint.get("phase") != "ready"
                or current_checkpoint.get("cursor") is not None
                or current_checkpoint.get("partition_count")
                != plan_summary.manifest_rows
                or current_checkpoint.get("batch_count") != plan_summary.batch_count
                or current.manifest_checksum != effective_checksum
                or current.last_key != plan_summary.last_key
            ):
                raise LegacyProjectionBootstrapError(
                    "peer ready compaction metadata is invalid"
                )
            transition_status = "already_ready"
            session.commit()
        elif current.state != "staging":
            raise LegacyProjectionBootstrapError("compaction ready transition lost ownership")
        else:
            if (
                current_checkpoint.get("partition_count")
                != checkpoint.get("partition_count")
                or current_checkpoint.get("batch_count") != checkpoint.get("batch_count")
                or current_checkpoint.get("cursor") != checkpoint.get("cursor")
            ):
                raise LegacyProjectionBootstrapError(
                    "compaction ready transition checkpoint changed"
                )
            active = session.scalar(
                select(SettlementProjectionActive.generation_id).where(
                    SettlementProjectionActive.projection_name == PROJECTION
                )
            )
            if _as_text(active) != base_generation_id:
                raise LegacyProjectionBootstrapError(
                    "compaction expected active base changed"
                )
            ready_checkpoint = _compaction_checkpoint(
                phase="ready",
                base_generation_id=base_generation_id,
                cursor=None,
                batch_size=threshold_config.batch_size,
                batch_count=int(checkpoint["batch_count"]),
                partition_count=plan_summary.manifest_rows,
                source_generation_count=len(lineage_rows),
                effective_checksum=effective_checksum,
                resource=resource,
            )
            current.state = "ready"
            current.checkpoint_json = ready_checkpoint
            current.manifest_checksum = effective_checksum
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        _close_session(session)
    generation = _load_generation(session_factory, generation_id)
    if generation is None:
        raise LegacyProjectionBootstrapError("ready compaction generation disappeared")
    return CompactionResult(
        generation_id=generation_id,
        status=transition_status,
        ready=True,
        resumed=resumed or transition_status == "already_ready",
        base_generation_id=base_generation_id,
        batch_count=int(checkpoint["batch_count"]),
        partition_count=plan_summary.manifest_rows,
        source_generation_count=len(lineage_rows),
        last_key=generation.last_key,
        manifest_checksum=effective_checksum,
        failure_code=None,
    )


def compact_projection_metadata(
    session_factory: Callable[[], Session],
    *,
    base_generation_id: str,
    threshold_config: CompactionThresholdConfig,
    resource_limits: ResourceGateConfig,
) -> CompactionResult:
    """Build a deterministic ready compact head without publishing it."""

    guard = _validate_compaction_arguments(
        base_generation_id, threshold_config, resource_limits
    )
    if guard is not None:
        return _compaction_guard(
            base_generation_id if isinstance(base_generation_id, str) else "", guard
        )
    generation_id: str | None = None
    try:
        result = _compact_projection_metadata_locked(
            session_factory,
            base_generation_id=base_generation_id,
            threshold_config=threshold_config,
            resource_limits=resource_limits,
        )
        generation_id = result.generation_id
        return result
    except LegacyProjectionBootstrapError:
        if generation_id is not None:
            _mark_failed(
                session_factory, generation_id, "compaction_failed", "metadata compaction failed"
            )
        raise
    except Exception as exc:
        raise LegacyProjectionBootstrapError("metadata compaction failed") from exc


__all__ = [
    "ResourceGateConfig",
    "CertificationResult",
    "CompactionThresholdConfig",
    "CompactionResult",
    "LegacyProjectionBootstrapError",
    "certify_legacy_null_root",
    "compact_projection_metadata",
]
