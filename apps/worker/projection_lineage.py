"""Read-only lineage resolution for sparse settlement projection readers.

The resolver deliberately keeps all lineage and manifest reads set based.  It is
used by API request readers before any aggregate rows are selected, and therefore
must fail closed when metadata is incomplete or corrupt.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Literal

from sqlalchemy import text


PartitionKey = str
SourceKind = Literal["overlay", "legacy_root", "tombstone"]

MAX_LINEAGE_DEPTH = 64
MAX_PARTITION_KEYS = 1000
_ARTIFACTS = {"monthly", "ranking", "score"}
_LOWER_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
# Strict signed-integer text form for manifest monetary/count fields.
_INTEGER_TEXT = re.compile(r"[+-]?[0-9]+\Z")
# Sentinel distinguishing "not read yet" from a negative (missing) cache entry.
_MANIFEST_MISSING = object()


def canonical_score_partition_key(
    snapshot_date: date | str, rule_version_id: str | None, store_id: str
) -> str:
    """Return an unambiguous score identity for sidecar/manifest readers."""

    date_value = snapshot_date.isoformat() if isinstance(snapshot_date, date) else str(snapshot_date)
    rule_value = _as_text(rule_version_id) or "legacy-unversioned"
    store_value = _as_text(store_id)
    if store_value is None:
        raise LineageError("score partition requires a store id")
    return f"{date_value}|{len(rule_value)}:{rule_value}|{len(store_value)}:{store_value}"


class LineageError(RuntimeError):
    """Fatal active-pointer, lineage, manifest, or database failure."""


# Keep a descriptive alias for callers/tests that used the longer name while the
# compact public name remains the primary contract.
ProjectionLineageError = LineageError


@dataclass(frozen=True)
class PartitionResolution:
    artifact: str
    partition_key: PartitionKey
    nearest_manifest_owner_generation: str | None
    actual_data_generation_id: str | None
    source_kind: SourceKind
    owner_state: str
    lineage_depth: int
    # The immutable generation ids considered by this resolution.  Score
    # sidecars use this to distinguish an authoritative tombstone in the
    # pinned lineage from an unrelated historical sidecar with the same key.
    lineage_generation_ids: frozenset[str] = frozenset()
    # Compact heads expose only the detached source selected for this exact
    # partition.  Ordinary lineages, tombstones, and legacy fallbacks keep the
    # set empty so existing readers remain backward-compatible.
    source_generation_ids: frozenset[str] = frozenset()

    @property
    def base_lineage_generation_ids(self) -> frozenset[str]:
        """Descriptive alias for the ordinary base-chain membership."""

        return self.lineage_generation_ids

    @property
    def data_generation_id(self) -> str | None:
        """Compatibility spelling used by overlay readers."""

        return self.actual_data_generation_id

    @property
    def owner_generation_id(self) -> str | None:
        return self.nearest_manifest_owner_generation

    @property
    def generation_id(self) -> str | None:
        return self.nearest_manifest_owner_generation


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _bounded_partition_keys(partition_keys: Iterable[PartitionKey]) -> list[PartitionKey]:
    result: list[PartitionKey] = []
    seen: set[str] = set()
    try:
        iterator = iter(partition_keys)
    except TypeError as exc:  # pragma: no cover - defensive contract guard
        raise LineageError("partition_keys must be an iterable of strings") from exc
    # Count both raw inputs and unique keys.  Counting raw inputs prevents a
    # duplicate-only infinite iterator from keeping a request alive forever;
    # counting unique keys enforces the actual SQL/query bound after dedupe.
    consumed = 0
    try:
        for value in iterator:
            consumed += 1
            if consumed > MAX_PARTITION_KEYS:
                raise LineageError(
                    f"partition key input exceeds maximum of {MAX_PARTITION_KEYS}"
                )
            normalized = _as_text(value)
            if normalized is None:
                raise LineageError("partition keys must be non-empty strings")
            if normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
                if len(result) > MAX_PARTITION_KEYS:
                    raise LineageError(
                        f"partition key input exceeds maximum of {MAX_PARTITION_KEYS}"
                    )
    except LineageError:
        raise
    except Exception as exc:
        raise LineageError("partition_keys iteration failed") from exc
    return result


def active_generation_id(session: Any) -> str | None:
    """Read the nullable settlement pointer once and validate its target.

    A missing row or a NULL pointer intentionally means that all readers retain
    their legacy-root behaviour.  Any non-NULL pointer must target a published
    settlement generation; dangling or non-published pointers are corruption.
    """

    try:
        result = session.execute(
            text(
                """
                SELECT a.generation_id,
                       g.generation_id AS target_generation_id,
                       g.projection_name,
                       g.state
                FROM settlement_projection_active AS a
                LEFT JOIN settlement_projection_generation AS g
                  ON g.generation_id = a.generation_id
                WHERE a.projection_name = :projection_name
                """
            ),
            {"projection_name": "settlement"},
        )
        row = result.mappings().first()
    except Exception as exc:
        raise LineageError("failed to read settlement active pointer") from exc

    if row is None or row.get("generation_id") is None:
        return None
    generation_id = _as_text(row.get("generation_id"))
    target_generation_id = _as_text(row.get("target_generation_id"))
    if (
        generation_id is None
        or target_generation_id != generation_id
        or _as_text(row.get("projection_name")) != "settlement"
        or _as_text(row.get("state")) != "published"
    ):
        raise LineageError("settlement active pointer is dangling or not published")
    return generation_id


def _manifest_params(prefix: str, values: list[str]) -> tuple[str, dict[str, str]]:
    params = {f"{prefix}_{index}": value for index, value in enumerate(values)}
    placeholders = ", ".join(f":{key}" for key in params)
    return placeholders, params


def _validate_manifest(
    row: dict[str, Any],
    lineage_ids: set[str],
    lineage_bases: dict[str, str | None],
) -> None:
    """Strict structural validation of one ordinary (non-compact) manifest row.

    Compact-owned manifest rows are not validated here: they are verified with
    the shared full compact provenance verifier, which reuses the same evidence
    and actual-row checks as the direct compact reader.
    """

    owner_state = _as_text(row.get("owner_state"))
    source_kind = _as_text(row.get("source_kind"))
    raw_data_generation_id = row.get("data_generation_id")
    data_generation_id = _as_text(raw_data_generation_id)
    owner_generation_id = _as_text(row.get("generation_id"))
    raw_manifest_base_generation_id = row.get("base_generation_id")
    manifest_base_generation_id = _as_text(raw_manifest_base_generation_id)
    reference_head_generation_id = _as_text(row.get("reference_head_generation_id"))
    if raw_data_generation_id is not None and data_generation_id is None:
        raise LineageError("manifest data generation id is blank")
    if (
        raw_manifest_base_generation_id is not None
        and manifest_base_generation_id is None
    ):
        raise LineageError("manifest base generation id is blank")
    row_count = _manifest_integer(row, "row_count")
    if owner_state == "owned" and source_kind == "overlay":
        if data_generation_id is None or data_generation_id not in lineage_ids:
            raise LineageError("overlay manifest has an invalid data generation")
    elif owner_state == "owned" and source_kind == "legacy_root":
        if data_generation_id is not None:
            raise LineageError("legacy-root manifest must not name data generation")
    elif owner_state == "tombstone" and source_kind == "tombstone":
        if data_generation_id is not None or row_count != 0:
            raise LineageError("tombstone manifest must have no data and zero rows")
    else:
        raise LineageError("manifest owner/source metadata is inconsistent")
    if reference_head_generation_id is not None:
        raise LineageError("ordinary manifest must not reference a compact head")
    if owner_generation_id is None:
        raise LineageError("manifest owner generation is missing")
    expected_base_generation_id = lineage_bases.get(owner_generation_id)
    if manifest_base_generation_id != expected_base_generation_id:
        raise LineageError("manifest base generation metadata is inconsistent")
    if manifest_base_generation_id is not None and manifest_base_generation_id not in lineage_ids:
        raise LineageError("manifest base generation is outside pinned lineage")


def _manifest_signed_integer(row: dict[str, Any], field: str) -> int:
    """Signed integer parse for monetary manifest fields.

    Amounts are signed: cross-month refund adjustments legitimately produce
    negative ``amount_total_cent`` totals.  Booleans and non-integer values
    still fail closed; negatives are never masked via abs/clamp or row drops.
    """

    value = row.get(field)
    if isinstance(value, bool):
        raise LineageError(f"manifest {field} is invalid")
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise LineageError(f"manifest {field} is invalid")
        return int(value)
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise LineageError(f"manifest {field} is invalid")
        return int(value)
    if isinstance(value, str) and _INTEGER_TEXT.fullmatch(value) is not None:
        # Parse through the arbitrary-precision int constructor, never float,
        # so large integer amounts keep full precision.
        return int(value)
    raise LineageError(f"manifest {field} is invalid")


def _manifest_integer(row: dict[str, Any], field: str) -> int:
    """Non-negative integer parse for counting manifest fields."""

    normalized = _manifest_signed_integer(row, field)
    if normalized < 0:
        raise LineageError(f"manifest {field} is invalid")
    return normalized


def _canonical_status_counts(value: Any) -> tuple[tuple[str, int], ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LineageError("manifest status counts are invalid") from exc
    if not isinstance(value, dict):
        raise LineageError("manifest status counts are invalid")
    normalized: list[tuple[str, int]] = []
    for raw_key, raw_count in value.items():
        if (
            not isinstance(raw_key, str)
            or not raw_key
            or type(raw_count) is not int
        ):
            raise LineageError("manifest status counts are invalid")
        count = raw_count
        if count < 0:
            raise LineageError("manifest status counts are invalid")
        normalized.append((raw_key, count))
    return tuple(sorted(normalized))


def _valid_digest(value: Any) -> str | None:
    if not isinstance(value, str) or value != value.strip():
        return None
    normalized = value
    if not normalized or _LOWER_HEX_64.fullmatch(normalized) is None:
        return None
    return normalized


_INHERITED_COMPACT_STATES = frozenset({"published", "superseded"})
_MANIFEST_BATCH_PAIRS = 400


@dataclass(frozen=True)
class _VerifiedCompactClosure:
    """Fully validated provenance closure of one compact generation."""

    compact_generation_id: str
    compaction_base_generation_id: str
    source_rows: dict[str, dict[str, Any]]
    source_ids: frozenset[str]
    compact_source_ids: tuple[str, ...]
    ordinary_source_ids: frozenset[str]


def _verify_compact_closure(
    session: Any,
    compact_generation_id: str,
    *,
    allowed_states: frozenset[str],
) -> _VerifiedCompactClosure:
    """Validate one compact head and its recorded provenance closure.

    The compact row itself must be a depth-zero settlement compact in one of
    the allowed states with a live published/superseded compaction base.  Every
    closure row must name the source's exact manifest digest (the digest pair
    is whatever algorithm produced the source's own manifest checksum), a
    settlement projection, a published/superseded state, and a shape that
    matches the source kind.  The closure is read with a bounded LIMIT and is
    never expanded transitively here; deeper provenance is proven through each
    compact source's own manifest rows at claim-verification time.
    """

    # One bounded query per compact node: head metadata, its compaction base,
    # and every closure/source row come back together via LEFT JOINs.  The
    # head is parsed from the first row; closure rows carry non-NULL
    # ``source_generation_id`` columns from the closure table itself, so a
    # compact with no closure rows yields a single all-NULL closure side.  The
    # LIMIT reads at most 66 rows (MAX_LINEAGE_DEPTH + 2) so a closure with
    # more than 65 sources exceeds the limit and fails closed below instead
    # of being silently truncated.
    try:
        rows_result = session.execute(
            text(
                """
                SELECT compact.generation_id AS compact_generation_id,
                       compact.projection_name AS compact_projection_name,
                       compact.state AS compact_state,
                       compact.generation_kind AS compact_generation_kind,
                       compact.base_generation_id AS compact_base_generation_id,
                       compact.compaction_base_generation_id
                         AS compact_compaction_base_generation_id,
                       compact.lineage_depth AS compact_lineage_depth,
                       base.generation_id AS base_generation_id,
                       base.projection_name AS base_projection_name,
                       base.state AS base_state,
                       closure.source_generation_id,
                       closure.source_digest,
                       source.projection_name AS source_projection_name,
                       source.state AS source_state,
                       source.generation_kind AS source_generation_kind,
                       source.base_generation_id AS source_base_generation_id,
                       source.compaction_base_generation_id
                         AS source_compaction_base_generation_id,
                       source.lineage_depth AS source_lineage_depth,
                       source.manifest_checksum AS source_manifest_checksum
                FROM settlement_projection_generation AS compact
                LEFT JOIN settlement_projection_generation AS base
                  ON base.generation_id = compact.compaction_base_generation_id
                LEFT JOIN settlement_projection_compaction_closure AS closure
                  ON closure.compact_generation_id = compact.generation_id
                LEFT JOIN settlement_projection_generation AS source
                  ON source.generation_id = closure.source_generation_id
                WHERE compact.generation_id = :compact_generation_id
                ORDER BY closure.source_generation_id
                LIMIT :row_limit
                """
            ),
            {
                "compact_generation_id": compact_generation_id,
                "row_limit": MAX_LINEAGE_DEPTH + 2,
            },
        )
        joined_rows = [dict(row) for row in rows_result.mappings().all()]
    except Exception as exc:
        raise LineageError("failed to read compact head metadata") from exc
    if not joined_rows:
        raise LineageError("compact head metadata is missing")
    head = joined_rows[0]
    compaction_base = _as_text(head.get("compact_compaction_base_generation_id"))
    try:
        head_depth = int(head.get("compact_lineage_depth") or 0)
    except (TypeError, ValueError) as exc:
        raise LineageError("compact head metadata is invalid") from exc
    if (
        _as_text(head.get("compact_generation_id")) != compact_generation_id
        or _as_text(head.get("compact_projection_name")) != "settlement"
        or _as_text(head.get("compact_state")) not in allowed_states
        or _as_text(head.get("compact_generation_kind")) != "compact"
        or head.get("compact_base_generation_id") is not None
        or compaction_base is None
        or compaction_base == compact_generation_id
        or head_depth != 0
    ):
        raise LineageError("compact head metadata is invalid")
    if (
        _as_text(head.get("base_generation_id")) != compaction_base
        or _as_text(head.get("base_projection_name")) != "settlement"
        or _as_text(head.get("base_state")) not in {"published", "superseded"}
    ):
        raise LineageError("compact provenance base is invalid")

    # Closure rows are the joined rows whose closure-side source id is set;
    # when the compact has no closure rows at all, the LEFT JOIN returns one
    # row with a NULL closure source id and head fields only.
    closure_rows = [
        row for row in joined_rows if row.get("source_generation_id") is not None
    ]
    if not closure_rows:
        raise LineageError("compact provenance closure is missing")
    source_rows: dict[str, dict[str, Any]] = {}
    compact_source_ids: list[str] = []
    ordinary_source_ids: set[str] = set()
    for row in closure_rows:
        source_id = _as_text(row.get("source_generation_id"))
        source_digest = _valid_digest(row.get("source_digest"))
        source_manifest_checksum = _valid_digest(row.get("source_manifest_checksum"))
        if (
            source_id is None
            or source_id == compact_generation_id
            or source_id in source_rows
        ):
            raise LineageError("compact provenance source identity is invalid")
        source_kind_name = _as_text(row.get("source_generation_kind"))
        if source_kind_name == "compact":
            # A compact closure source must itself be a verified terminal
            # compact head: NULL base, depth 0, provenance present.
            provenance_ok = (
                row.get("source_compaction_base_generation_id") is not None
                and row.get("source_base_generation_id") is None
            )
        else:
            provenance_ok = (
                source_kind_name in {"lineage", "legacy_root"}
                and row.get("source_compaction_base_generation_id") is None
            )
        if (
            source_digest is None
            or source_manifest_checksum is None
            or source_digest != source_manifest_checksum
            or _as_text(row.get("source_projection_name")) != "settlement"
            or _as_text(row.get("source_state")) not in {"published", "superseded"}
            or not provenance_ok
        ):
            raise LineageError("compact provenance source metadata is invalid")
        try:
            source_depth = int(row.get("source_lineage_depth") or 0)
        except (TypeError, ValueError) as exc:
            raise LineageError("compact provenance source depth is invalid") from exc
        if source_depth < 0 or source_depth > MAX_LINEAGE_DEPTH:
            raise LineageError("compact provenance source depth is invalid")
        if source_kind_name == "legacy_root" and (
            row.get("source_base_generation_id") is not None or source_depth != 0
        ):
            raise LineageError("compact legacy-root source metadata is invalid")
        if source_kind_name == "compact":
            if source_depth != 0:
                raise LineageError("compact provenance source depth is invalid")
            compact_source_ids.append(source_id)
        else:
            ordinary_source_ids.add(source_id)
        source_rows[source_id] = row
    if len(source_rows) > MAX_LINEAGE_DEPTH + 1:
        raise LineageError("compact provenance exceeds maximum source count")
    return _VerifiedCompactClosure(
        compact_generation_id=compact_generation_id,
        compaction_base_generation_id=compaction_base,
        source_rows=source_rows,
        source_ids=frozenset(source_rows),
        compact_source_ids=tuple(compact_source_ids),
        ordinary_source_ids=frozenset(ordinary_source_ids),
    )


class _CompactProvenanceContext:
    """Bounded, batched, request-reusable compact provenance verifier.

    One context serves one read request (or one compaction verification
    sweep): verified closures, anchor/source manifests, and actual data-row
    presence facts are read in fixed-size batches and reused by every
    partition that needs them, so query counts stay independent of the
    partition count.  The number of unique compact nodes opened for a request
    and the depth of any provenance walk are bounded by ``MAX_LINEAGE_DEPTH``;
    exceeding either budget, or revisiting a compact node on one provenance
    path, fails closed instead of expanding the closure.
    """

    def __init__(self, session: Any) -> None:
        self.session = session
        self._closures: dict[str, _VerifiedCompactClosure] = {}
        self._manifests: dict[
            tuple[str, str, str], dict[str, Any] | None
        ] = {}
        self._presence: dict[tuple[str, str, str], int] = {}
        self._verified: set[tuple[str, str, str]] = set()
        self._opened_compacts: set[str] = set()

    def verified_closure(
        self,
        compact_generation_id: str,
        *,
        allowed_states: frozenset[str],
    ) -> _VerifiedCompactClosure:
        cached = self._closures.get(compact_generation_id)
        if cached is not None:
            return cached
        self._opened_compacts.add(compact_generation_id)
        if len(self._opened_compacts) > MAX_LINEAGE_DEPTH:
            raise LineageError(
                "compact provenance exceeds maximum compact node count"
            )
        closure = _verify_compact_closure(
            self.session,
            compact_generation_id,
            allowed_states=frozenset(allowed_states),
        )
        self._closures[compact_generation_id] = closure
        return closure

    def verify_compact_partition_claims(
        self,
        claims: list[tuple[str, str, dict[str, Any]]],
        *,
        artifact: str,
    ) -> None:
        """Verify compact-owned overlay manifest rows down to their real leaf.

        Each claim is one compact-owned overlay manifest row
        ``(compact_generation_id, partition_key, manifest_row)``.  A leaf
        directly captured by an ordinary source is proven against that
        source's own manifest row plus the presence of its actual data rows;
        a leaf inherited from a captured compact source is proven through the
        anchor compact's manifest row for the same artifact/partition and that
        anchor's own provenance.  All reads per level are fixed-size batches,
        verified results are reused for the rest of the request, and the real
        ``data_generation_id`` is always the original leaf overlay generation —
        never a metadata compact id.
        """

        pending: list[tuple[tuple[str, ...], str, str, dict[str, Any]]] = [
            ((compact_generation_id,), compact_generation_id, partition_key, row)
            for compact_generation_id, partition_key, row in claims
        ]
        presence_requirements: dict[tuple[str, str], int] = {}
        while pending:
            closures: dict[str, _VerifiedCompactClosure] = {}
            active: list[
                tuple[
                    tuple[str, ...],
                    str,
                    str,
                    dict[str, Any],
                    str,
                    _VerifiedCompactClosure,
                ]
            ] = []
            for path, compact_id, partition_key, row in pending:
                closure = closures.get(compact_id)
                if closure is None:
                    closure = self.verified_closure(
                        compact_id, allowed_states=_INHERITED_COMPACT_STATES
                    )
                    closures[compact_id] = closure
                data_generation_id = _as_text(row.get("data_generation_id"))
                if _as_text(row.get("base_generation_id")) is not None:
                    raise LineageError("compact manifest base generation must be null")
                if (
                    _as_text(row.get("owner_state")) != "owned"
                    or _as_text(row.get("source_kind")) != "overlay"
                ):
                    raise LineageError(
                        "compact manifest owner/source metadata is invalid"
                    )
                if (
                    data_generation_id is None
                    or _as_text(row.get("reference_head_generation_id")) != compact_id
                    or _valid_digest(row.get("checksum")) is None
                ):
                    raise LineageError(
                        "compact manifest provenance reference is invalid"
                    )
                if (compact_id, artifact, partition_key) in self._verified:
                    continue
                active.append(
                    (path, compact_id, partition_key, row, data_generation_id, closure)
                )
            if not active:
                break
            overlay_pairs = sorted(
                {
                    (data_generation_id, partition_key)
                    for _, _, partition_key, _, data_generation_id, closure in active
                    if data_generation_id in closure.ordinary_source_ids
                }
            )
            anchor_pairs: set[tuple[str, str]] = set()
            for _, _, partition_key, _, data_generation_id, closure in active:
                if data_generation_id in closure.ordinary_source_ids:
                    continue
                if not closure.compact_source_ids:
                    raise LineageError(
                        "compact manifest provenance reference is invalid"
                    )
                anchor_pairs.update(
                    (anchor_id, partition_key)
                    for anchor_id in closure.compact_source_ids
                )
            source_manifests = self._manifest_rows(artifact, overlay_pairs)
            anchor_manifests = self._manifest_rows(artifact, sorted(anchor_pairs))
            next_pending: list[
                tuple[tuple[str, ...], str, str, dict[str, Any]]
            ] = []
            for (
                path,
                compact_id,
                partition_key,
                row,
                data_generation_id,
                closure,
            ) in active:
                if data_generation_id in closure.ordinary_source_ids:
                    identity = (data_generation_id, partition_key)
                    source_manifest = source_manifests.get(identity)
                    if source_manifest is None:
                        raise LineageError("compact source manifest is missing")
                    source_facts = closure.source_rows[data_generation_id]
                    if (
                        _as_text(source_manifest.get("owner_state")) != "owned"
                        or _as_text(source_manifest.get("source_kind")) != "overlay"
                        or _as_text(source_manifest.get("data_generation_id"))
                        != data_generation_id
                        or source_manifest.get("reference_head_generation_id")
                        is not None
                        or _as_text(source_manifest.get("base_generation_id"))
                        != _as_text(source_facts.get("source_base_generation_id"))
                        or _valid_digest(source_manifest.get("checksum"))
                        != _valid_digest(row.get("checksum"))
                        or _manifest_integer(source_manifest, "row_count")
                        != _manifest_integer(row, "row_count")
                        or _manifest_signed_integer(source_manifest, "amount_total_cent")
                        != _manifest_signed_integer(row, "amount_total_cent")
                        or _canonical_status_counts(
                            source_manifest.get("status_counts_json")
                        )
                        != _canonical_status_counts(row.get("status_counts_json"))
                    ):
                        raise LineageError(
                            "compact source manifest evidence does not match"
                        )
                    self._require_presence(
                        presence_requirements,
                        data_generation_id,
                        partition_key,
                        _manifest_integer(row, "row_count"),
                    )
                    self._verified.add((compact_id, artifact, partition_key))
                    continue
                matches: list[tuple[str, dict[str, Any]]] = []
                for anchor_id in closure.compact_source_ids:
                    candidate = anchor_manifests.get((anchor_id, partition_key))
                    if candidate is None:
                        continue
                    if _as_text(candidate.get("data_generation_id")) != data_generation_id:
                        continue
                    matches.append((anchor_id, candidate))
                if len(matches) > 1:
                    raise LineageError("compact anchor manifest identity is invalid")
                if not matches:
                    raise LineageError(
                        "compact manifest provenance reference is invalid"
                    )
                anchor_id, anchor_row = matches[0]
                if anchor_id in path:
                    raise LineageError("compact provenance path contains a cycle")
                if (
                    _as_text(anchor_row.get("owner_state"))
                    != _as_text(row.get("owner_state"))
                    or _as_text(anchor_row.get("source_kind"))
                    != _as_text(row.get("source_kind"))
                    or _as_text(anchor_row.get("data_generation_id"))
                    != _as_text(row.get("data_generation_id"))
                    or _as_text(anchor_row.get("base_generation_id"))
                    != _as_text(row.get("base_generation_id"))
                    or _as_text(anchor_row.get("base_generation_id"))
                    != _as_text(
                        closure.source_rows[anchor_id].get(
                            "source_base_generation_id"
                        )
                    )
                    or _manifest_integer(anchor_row, "row_count")
                    != _manifest_integer(row, "row_count")
                    or _manifest_signed_integer(anchor_row, "amount_total_cent")
                    != _manifest_signed_integer(row, "amount_total_cent")
                    or _canonical_status_counts(anchor_row.get("status_counts_json"))
                    != _canonical_status_counts(row.get("status_counts_json"))
                    or _as_text(anchor_row.get("checksum"))
                    != _as_text(row.get("checksum"))
                ):
                    raise LineageError(
                        "compact source manifest evidence does not match"
                    )
                self._require_presence(
                    presence_requirements,
                    data_generation_id,
                    partition_key,
                    _manifest_integer(row, "row_count"),
                )
                self._verified.add((compact_id, artifact, partition_key))
                next_pending.append(
                    (
                        (*path, anchor_id),
                        anchor_id,
                        partition_key,
                        anchor_row,
                    )
                )
            pending = next_pending
        self._verify_presence(artifact, presence_requirements)

    def _manifest_rows(
        self, artifact: str, pairs: list[tuple[str, str]]
    ) -> dict[tuple[str, str], dict[str, Any] | None]:
        """Batched, cached manifest read for (generation, partition) pairs."""

        resolved: dict[tuple[str, str], dict[str, Any] | None] = {}
        needed: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for pair in pairs:
            if pair in seen:
                continue
            seen.add(pair)
            cached = self._manifests.get(
                (artifact, pair[0], pair[1]), _MANIFEST_MISSING
            )
            if cached is not _MANIFEST_MISSING:
                resolved[pair] = cached
            else:
                needed.append(pair)
        for batch_index in range(0, len(needed), _MANIFEST_BATCH_PAIRS):
            batch = needed[batch_index : batch_index + _MANIFEST_BATCH_PAIRS]
            clauses: list[str] = []
            params: dict[str, str] = {"provenance_artifact": artifact}
            for pair_index, (generation_id, partition_key) in enumerate(batch):
                generation_param = f"provenance_generation_{batch_index}_{pair_index}"
                partition_param = f"provenance_partition_{batch_index}_{pair_index}"
                clauses.append(
                    f"(generation_id = :{generation_param} "
                    f"AND partition_key = :{partition_param})"
                )
                params[generation_param] = generation_id
                params[partition_param] = partition_key
            try:
                result = self.session.execute(
                    text(
                        """
                        SELECT generation_id, artifact, partition_key, owner_state,
                               source_kind, data_generation_id, base_generation_id,
                               reference_head_generation_id, row_count,
                               amount_total_cent, status_counts_json, checksum
                        FROM settlement_projection_partition_manifest
                        WHERE artifact = :provenance_artifact
                          AND ("""
                        + " OR ".join(clauses)
                        + ")"
                    ),
                    params,
                )
                rows = [dict(row) for row in result.mappings().all()]
            except Exception as exc:
                raise LineageError(
                    "failed to read compact provenance manifests"
                ) from exc
            for row in rows:
                identity = (
                    _as_text(row.get("generation_id")),
                    _as_text(row.get("partition_key")),
                )
                if None in identity:
                    raise LineageError(
                        "compact provenance manifest identity is invalid"
                    )
                pair = (identity[0], identity[1])
                if resolved.get(pair) is not None:
                    raise LineageError(
                        "compact provenance manifest identity is invalid"
                    )
                resolved[pair] = row
                self._manifests[(artifact, pair[0], pair[1])] = row
        for pair in needed:
            if pair not in resolved:
                resolved[pair] = None
                self._manifests[(artifact, pair[0], pair[1])] = None
        return resolved

    def _require_presence(
        self,
        requirements: dict[tuple[str, str], int],
        data_generation_id: str,
        partition_key: str,
        row_count: int,
    ) -> None:
        identity = (data_generation_id, partition_key)
        existing = requirements.get(identity)
        if existing is not None and existing != row_count:
            raise LineageError("compact provenance evidence conflicts on one partition")
        requirements[identity] = row_count

    def _verify_presence(
        self, artifact: str, requirements: dict[tuple[str, str], int]
    ) -> None:
        if not requirements:
            return
        if artifact == "monthly":
            table = "settlement_monthly_overlay"
            tombstone_clause = "AND (tombstone = FALSE OR tombstone IS NULL)"
        elif artifact == "ranking":
            table = "settlement_ranking_overlay"
            tombstone_clause = "AND (tombstone = FALSE OR tombstone IS NULL)"
        else:
            table = "store_score_snapshot_generation"
            tombstone_clause = ""
        pending: list[tuple[str, str]] = []
        for identity, row_count in requirements.items():
            cached = self._presence.get(
                (artifact, identity[0], identity[1]), _MANIFEST_MISSING
            )
            if cached is _MANIFEST_MISSING:
                pending.append(identity)
            elif cached != row_count:
                raise LineageError(
                    "compact source row count does not match manifest"
                )
        present: dict[tuple[str, str], int] = {}
        for batch_index in range(0, len(pending), _MANIFEST_BATCH_PAIRS):
            batch = pending[batch_index : batch_index + _MANIFEST_BATCH_PAIRS]
            generation_values = sorted({generation for generation, _ in batch})
            partition_values = sorted({partition for _, partition in batch})
            generation_placeholders, generation_params = _manifest_params(
                f"provenance_presence_generation_{batch_index}", generation_values
            )
            partition_placeholders, partition_params = _manifest_params(
                f"provenance_presence_partition_{batch_index}", partition_values
            )
            try:
                result = self.session.execute(
                    text(
                        f"""
                        SELECT generation_id, partition_key, COUNT(*) AS present_count
                        FROM {table}
                        WHERE generation_id IN ({generation_placeholders})
                          AND partition_key IN ({partition_placeholders})
                          {tombstone_clause}
                        GROUP BY generation_id, partition_key
                        """
                    ),
                    {**generation_params, **partition_params},
                )
                for row in result.mappings().all():
                    present[
                        (
                            _as_text(row.get("generation_id")) or "",
                            _as_text(row.get("partition_key")) or "",
                        )
                    ] = int(row.get("present_count") or 0)
            except Exception as exc:
                raise LineageError("failed to validate compact source rows") from exc
        for identity in pending:
            actual = present.get(identity, 0)
            self._presence[(artifact, identity[0], identity[1])] = actual
            if actual != requirements[identity]:
                raise LineageError("compact source row count does not match manifest")


def _resolve_compact_partitions(
    session: Any,
    *,
    artifact: str,
    keys: list[str],
    pinned: str,
    head: dict[str, Any],
    provenance_context: "_CompactProvenanceContext | None" = None,
) -> dict[str, PartitionResolution]:
    if (
        _as_text(head.get("generation_id")) != pinned
        or _as_text(head.get("projection_name")) != "settlement"
        or _as_text(head.get("state")) != "published"
        or _as_text(head.get("generation_kind")) != "compact"
        or head.get("base_generation_id") is not None
        or int(head.get("lineage_depth") or 0) != 0
    ):
        raise LineageError("compact head metadata is invalid")
    compaction_base = _as_text(head.get("compaction_base_generation_id"))
    if compaction_base is None or compaction_base == pinned:
        raise LineageError("compact head base metadata is invalid")

    context = (
        provenance_context
        if provenance_context is not None
        else _CompactProvenanceContext(session)
    )
    # The pinned compact head keeps its stricter published-only state gate;
    # the shared verifier proves the closure digest/projection/state/shape
    # facts once and reuses them for every partition in this request.
    closure = context.verified_closure(
        pinned, allowed_states=frozenset({"published"})
    )
    if closure.compaction_base_generation_id != compaction_base:
        raise LineageError("compact provenance base is invalid")

    head_manifests: dict[str, dict[str, Any]] = {}
    for batch_index in range(0, len(keys), 400):
        batch = keys[batch_index : batch_index + 400]
        placeholders, params = _manifest_params(f"compact_partition_{batch_index}", batch)
        try:
            result = session.execute(
                text(
                    f"""
                    SELECT generation_id, artifact, partition_key, owner_state,
                           source_kind, data_generation_id, base_generation_id,
                           reference_head_generation_id, row_count,
                           amount_total_cent, status_counts_json, checksum
                    FROM settlement_projection_partition_manifest
                    WHERE generation_id = :compact_head
                      AND artifact = :compact_artifact
                      AND partition_key IN ({placeholders})
                    """
                ),
                {
                    "compact_head": pinned,
                    "compact_artifact": artifact,
                    **params,
                },
            )
            rows = [dict(row) for row in result.mappings().all()]
        except Exception as exc:
            raise LineageError("failed to read compact partition manifests") from exc
        for row in rows:
            partition_key = _as_text(row.get("partition_key"))
            if partition_key is None or partition_key in head_manifests:
                raise LineageError("compact manifest identity is invalid")
            head_manifests[partition_key] = row

    resolutions: dict[str, PartitionResolution] = {}
    claims: list[tuple[str, str, dict[str, Any]]] = []
    for key in keys:
        manifest = head_manifests.get(key)
        if manifest is None:
            resolutions[key] = PartitionResolution(
                artifact=artifact,
                partition_key=key,
                nearest_manifest_owner_generation=None,
                actual_data_generation_id=None,
                source_kind="legacy_root",
                owner_state="legacy_root",
                lineage_depth=0,
                lineage_generation_ids=frozenset({pinned}),
            )
            continue
        owner_state = _as_text(manifest.get("owner_state"))
        source_kind = _as_text(manifest.get("source_kind"))
        data_generation_id = _as_text(manifest.get("data_generation_id"))
        reference_head = _as_text(manifest.get("reference_head_generation_id"))
        if manifest.get("base_generation_id") is not None:
            raise LineageError("compact manifest base generation must be null")
        if owner_state == "tombstone" and source_kind == "tombstone":
            if (
                data_generation_id is not None
                or reference_head is not None
                or _manifest_integer(manifest, "row_count") != 0
            ):
                raise LineageError("compact tombstone manifest is invalid")
            resolutions[key] = PartitionResolution(
                artifact=artifact,
                partition_key=key,
                nearest_manifest_owner_generation=pinned,
                actual_data_generation_id=None,
                source_kind="tombstone",
                owner_state="tombstone",
                lineage_depth=0,
                lineage_generation_ids=frozenset({pinned}),
            )
            continue
        if owner_state != "owned" or source_kind != "overlay":
            raise LineageError("compact manifest owner/source metadata is invalid")
        if (
            data_generation_id is None
            or reference_head != pinned
            or _valid_digest(manifest.get("checksum")) is None
        ):
            raise LineageError("compact manifest provenance reference is invalid")
        # The shared verifier proves this row down to the real leaf provenance:
        # either the leaf is directly captured by an ordinary closure source
        # (manifest evidence + actual data rows) or it is inherited through the
        # compact closure sources' own verified manifest rows.
        claims.append((pinned, key, manifest))
        resolutions[key] = PartitionResolution(
            artifact=artifact,
            partition_key=key,
            nearest_manifest_owner_generation=pinned,
            actual_data_generation_id=data_generation_id,
            source_kind="overlay",
            owner_state="owned",
            lineage_depth=0,
            lineage_generation_ids=frozenset({pinned}),
            source_generation_ids=frozenset({data_generation_id}),
        )

    if claims:
        context.verify_compact_partition_claims(claims, artifact=artifact)
    return resolutions


def resolve_projection_partitions(
    session: Any,
    *,
    artifact: str,
    partition_keys: Iterable[PartitionKey],
    pinned_generation_id: str | None,
    provenance_context: "_CompactProvenanceContext | None" = None,
) -> dict[PartitionKey, PartitionResolution]:
    """Resolve each requested partition to exactly one source.

    For a NULL pinned generation this is a pure legacy-root fallback and does not
    touch the database.  For a pinned generation one bounded recursive query
    reads its immutable lineage and one batched manifest query resolves all keys.
    ``provenance_context`` lets a caller (for example the compaction builder's
    per-page sweep) reuse one verified provenance context across several
    artifact resolutions; every request creates its own bounded context anyway.
    """

    normalized_artifact = _as_text(artifact)
    if normalized_artifact not in _ARTIFACTS:
        raise LineageError(f"unsupported projection artifact: {artifact!r}")
    keys = _bounded_partition_keys(partition_keys)
    if not keys:
        return {}
    # ``NULL`` intentionally keeps the legacy-root compatibility path, while a
    # supplied blank identifier is malformed input and must fail closed.  Do
    # not normalize both values into the same fallback state.
    if pinned_generation_id is not None and _as_text(pinned_generation_id) is None:
        raise LineageError("pinned generation id must be a non-empty string")
    pinned = _as_text(pinned_generation_id)
    if pinned is None:
        return {
            key: PartitionResolution(
                artifact=normalized_artifact,
                partition_key=key,
                nearest_manifest_owner_generation=None,
                actual_data_generation_id=None,
                source_kind="legacy_root",
                owner_state="legacy_root",
                lineage_depth=0,
                lineage_generation_ids=frozenset(),
            )
            for key in keys
        }

    try:
        lineage_result = session.execute(
            text(
                """
                WITH RECURSIVE projection_lineage AS (
                    SELECT generation_id,
                           base_generation_id,
                           generation_kind,
                           compaction_base_generation_id,
                           projection_name,
                           state,
                           lineage_depth,
                           manifest_checksum,
                           0 AS hop
                    FROM settlement_projection_generation
                    WHERE generation_id = :pinned_generation_id
                    UNION ALL
                    SELECT generation.generation_id,
                           generation.base_generation_id,
                           generation.generation_kind,
                           generation.compaction_base_generation_id,
                           generation.projection_name,
                           generation.state,
                           generation.lineage_depth,
                           generation.manifest_checksum,
                           projection_lineage.hop + 1
                    FROM settlement_projection_generation AS generation
                    JOIN projection_lineage
                      ON generation.generation_id = projection_lineage.base_generation_id
                    WHERE projection_lineage.hop < :max_lineage_depth
                )
                SELECT generation_id, base_generation_id, generation_kind,
                       compaction_base_generation_id, projection_name,
                       state, lineage_depth, manifest_checksum, hop
                FROM projection_lineage
                ORDER BY hop
                """
            ),
            {
                "pinned_generation_id": pinned,
                "max_lineage_depth": MAX_LINEAGE_DEPTH,
            },
        )
        lineage_rows = [dict(row) for row in lineage_result.mappings().all()]
    except Exception as exc:
        raise LineageError("failed to read projection lineage") from exc

    if not lineage_rows:
        raise LineageError("pinned generation does not exist")
    if len(lineage_rows) > MAX_LINEAGE_DEPTH + 1:
        raise LineageError("projection lineage exceeds maximum depth")

    if _as_text(lineage_rows[0].get("generation_kind")) == "compact":
        if len(lineage_rows) != 1:
            raise LineageError("compact head must not have an ordinary base chain")
        return _resolve_compact_partitions(
            session,
            artifact=normalized_artifact,
            keys=keys,
            pinned=pinned,
            head=lineage_rows[0],
            provenance_context=provenance_context,
        )

    lineage_ids: set[str] = set()
    try:
        pinned_metadata_depth = int(lineage_rows[0].get("lineage_depth") or 0)
    except (TypeError, ValueError) as exc:
        raise LineageError("projection lineage depth is invalid") from exc
    if pinned_metadata_depth < 0 or pinned_metadata_depth > MAX_LINEAGE_DEPTH:
        raise LineageError("projection lineage depth is invalid")
    # Metadata depth is an absolute value, not merely a relative decrement
    # from the pinned node.  A complete chain of N edges must therefore contain
    # N + 1 rows, end at depth zero, and start at depth N.
    if pinned_metadata_depth != len(lineage_rows) - 1:
        raise LineageError("projection lineage depth does not match complete chain")
    previous_generation: str | None = None
    for index, row in enumerate(lineage_rows):
        generation_id = _as_text(row.get("generation_id"))
        if generation_id is None:
            raise LineageError("projection lineage contains an empty generation id")
        if generation_id in lineage_ids:
            raise LineageError("projection lineage contains a cycle")
        lineage_ids.add(generation_id)
        raw_base_generation_id = row.get("base_generation_id")
        if raw_base_generation_id is not None and _as_text(raw_base_generation_id) is None:
            raise LineageError("projection lineage contains an empty base generation id")
        if _as_text(row.get("projection_name")) != "settlement":
            raise LineageError("projection lineage contains another projection")
        generation_kind = _as_text(row.get("generation_kind"))
        if generation_kind == "compact":
            # A compact generation may terminate an ordinary chain after later
            # daily finalizes rebuilt on top of it.  It must be the terminal
            # row; depth 0 is enforced by the hop arithmetic below and the
            # provenance must be present.
            if index != len(lineage_rows) - 1:
                raise LineageError(
                    "ordinary lineage contains an invalid generation kind"
                )
            if row.get("base_generation_id") is not None:
                raise LineageError("compact ancestor base metadata is invalid")
            if row.get("compaction_base_generation_id") is None:
                raise LineageError("compact ancestor provenance is invalid")
        elif generation_kind not in {"lineage", "legacy_root"}:
            raise LineageError("ordinary lineage contains an invalid generation kind")
        if generation_kind != "compact" and row.get("compaction_base_generation_id") is not None:
            raise LineageError("ordinary lineage contains compact provenance metadata")
        state = _as_text(row.get("state"))
        if index == 0:
            if generation_id != pinned or state != "published":
                raise LineageError("pinned generation is not published")
        elif state not in {"published", "superseded"}:
            raise LineageError("projection lineage contains a non-published base")
        try:
            hop = int(row.get("hop") or 0)
            metadata_depth = int(row.get("lineage_depth") or 0)
        except (TypeError, ValueError) as exc:
            raise LineageError("projection lineage depth is invalid") from exc
        if (
            hop > MAX_LINEAGE_DEPTH
            or metadata_depth < 0
            or metadata_depth > MAX_LINEAGE_DEPTH
            or metadata_depth != pinned_metadata_depth - hop
        ):
            raise LineageError("projection lineage depth is invalid")
        if previous_generation is not None:
            expected_base = _as_text(lineage_rows[index - 1].get("base_generation_id"))
            if expected_base != generation_id:
                raise LineageError("projection lineage has inconsistent base metadata")
        previous_generation = generation_id

    terminal_base = _as_text(lineage_rows[-1].get("base_generation_id"))
    if terminal_base is not None:
        if terminal_base in lineage_ids:
            raise LineageError("projection lineage contains a cycle")
        raise LineageError("projection lineage references a missing base generation")

    # When the chain terminates in a compact ancestor, the compact-owned
    # partitions are verified with the exact same full provenance verifier the
    # direct compact reader uses: closure digests, source projection/state and
    # shapes, manifest evidence down to the real leaf, and actual data rows.
    # The verifier is fail-closed and bounded; membership alone is never
    # sufficient to accept a compact-owned partition.
    compact_owner_generation_id: str | None = None
    if _as_text(lineage_rows[-1].get("generation_kind")) == "compact":
        compact_owner_generation_id = _as_text(lineage_rows[-1]["generation_id"])
        if compact_owner_generation_id is None:
            raise LineageError("ordinary lineage contains an invalid generation kind")
        context = (
            provenance_context
            if provenance_context is not None
            else _CompactProvenanceContext(session)
        )
        # Validate the terminal compact's closure unconditionally so corrupted
        # provenance fails closed even when the requested keys resolve to
        # ordinary owners.
        context.verified_closure(
            compact_owner_generation_id, allowed_states=_INHERITED_COMPACT_STATES
        )
    else:
        context = (
            provenance_context
            if provenance_context is not None
            else _CompactProvenanceContext(session)
        )

    # Keep each manifest statement below SQLite's traditional 999-variable
    # limit.  A public request may contain 1,000 keys and a complete lineage
    # may contain up to 65 generation ids, so a single ``IN`` would bind more
    # than 1,066 values.  Every key stays in one batch, preserving duplicate
    # detection across all returned rows while keeping query count independent
    # of individual partitions.
    manifest_rows: list[dict[str, Any]] = []
    generation_values = list(lineage_ids)
    generation_placeholders, generation_params = _manifest_params(
        "manifest_generation", generation_values
    )
    for batch_index in range(0, len(keys), 400):
        key_batch = keys[batch_index : batch_index + 400]
        key_placeholders, key_params = _manifest_params(
            f"manifest_partition_{batch_index}", key_batch
        )
        try:
            manifest_result = session.execute(
                text(
                    f"""
                    SELECT generation_id, artifact, partition_key, owner_state,
                           source_kind, data_generation_id, base_generation_id,
                           reference_head_generation_id, row_count,
                           amount_total_cent, status_counts_json, checksum
                    FROM settlement_projection_partition_manifest
                    WHERE artifact = :manifest_artifact
                      AND generation_id IN ({generation_placeholders})
                      AND partition_key IN ({key_placeholders})
                    """
                ),
                {
                    "manifest_artifact": normalized_artifact,
                    **generation_params,
                    **key_params,
                },
            )
            manifest_rows.extend(dict(row) for row in manifest_result.mappings().all())
        except Exception as exc:
            raise LineageError("failed to read projection partition manifest") from exc

    by_generation_and_key: dict[tuple[str, str], dict[str, Any]] = {}
    lineage_bases = {
        _as_text(row.get("generation_id")): _as_text(row.get("base_generation_id"))
        for row in lineage_rows
        if _as_text(row.get("generation_id")) is not None
    }
    compact_claims: list[tuple[str, str, dict[str, Any]]] = []
    for row in manifest_rows:
        generation_id = _as_text(row.get("generation_id"))
        partition_key = _as_text(row.get("partition_key"))
        if generation_id is None or partition_key is None:
            raise LineageError("manifest contains an empty identity")
        if generation_id not in lineage_ids:
            raise LineageError("manifest owner is outside pinned lineage")
        if generation_id == compact_owner_generation_id:
            owner_state = _as_text(row.get("owner_state"))
            source_kind = _as_text(row.get("source_kind"))
            if owner_state == "owned" and source_kind == "overlay":
                # Verified with the shared full compact provenance verifier.
                compact_claims.append((generation_id, partition_key, row))
            elif owner_state == "tombstone" and source_kind == "tombstone":
                _validate_manifest(row, lineage_ids, lineage_bases)
            else:
                raise LineageError("compact manifest owner/source metadata is invalid")
        else:
            _validate_manifest(row, lineage_ids, lineage_bases)
        identity = (generation_id, partition_key)
        if identity in by_generation_and_key:
            raise LineageError("duplicate partition manifest row")
        by_generation_and_key[identity] = row
    if compact_owner_generation_id is not None:
        context.verify_compact_partition_claims(
            compact_claims, artifact=normalized_artifact
        )

    resolutions: dict[PartitionKey, PartitionResolution] = {}
    for key in keys:
        selected: dict[str, Any] | None = None
        selected_generation: str | None = None
        selected_hop = 0
        for hop, row in enumerate(lineage_rows):
            generation_id = _as_text(row.get("generation_id"))
            if generation_id is None:
                continue
            candidate = by_generation_and_key.get((generation_id, key))
            if candidate is not None:
                selected = candidate
                selected_generation = generation_id
                selected_hop = hop
                break
        if selected is None:
            resolutions[key] = PartitionResolution(
                artifact=normalized_artifact,
                partition_key=key,
                nearest_manifest_owner_generation=None,
                actual_data_generation_id=None,
                source_kind="legacy_root",
                owner_state="legacy_root",
                lineage_depth=0,
                lineage_generation_ids=frozenset(lineage_ids),
            )
            continue
        source_kind = _as_text(selected.get("source_kind"))
        owner_state = _as_text(selected.get("owner_state"))
        if source_kind not in {"overlay", "legacy_root", "tombstone"}:
            raise LineageError("manifest source kind is invalid")
        if owner_state is None:
            raise LineageError("manifest owner state is invalid")
        resolutions[key] = PartitionResolution(
            artifact=normalized_artifact,
            partition_key=key,
            nearest_manifest_owner_generation=selected_generation,
            actual_data_generation_id=_as_text(selected.get("data_generation_id")),
            source_kind=source_kind,  # type: ignore[arg-type]
            owner_state=owner_state,
            lineage_depth=selected_hop,
            lineage_generation_ids=frozenset(lineage_ids),
        )

    # A manifest that claims non-zero overlay data must have at least one
    # corresponding row in the generation-scoped table.  The check is batched
    # across all selected partitions and artifacts, so it remains independent
    # of partition count and never degenerates into an endpoint N+1 loop.
    # Compact-owned partitions are already presence-verified (including their
    # real leaf rows) by the shared provenance verifier above.
    overlay_requirements: list[tuple[str, str, str]] = []
    for key, resolution in resolutions.items():
        if resolution.source_kind != "overlay" or resolution.actual_data_generation_id is None:
            continue
        owner_generation = resolution.nearest_manifest_owner_generation
        if owner_generation is None:
            raise LineageError("overlay partition has no manifest owner")
        if (
            compact_owner_generation_id is not None
            and owner_generation == compact_owner_generation_id
        ):
            continue
        manifest = by_generation_and_key.get((owner_generation, key))
        if manifest is None:
            raise LineageError("overlay partition manifest disappeared")
        try:
            row_count = _manifest_integer(manifest, "row_count")
        except LineageError:
            raise
        if row_count > 0:
            overlay_requirements.append(
                (normalized_artifact, resolution.actual_data_generation_id, key)
            )
    if overlay_requirements:
        # One grouped set query per fixed-size batch keeps SQL shape constant
        # and avoids SQLite's MAX_COMPOUND_SELECT limit.  At most three batches
        # are possible for the public 1000-key resolver bound.
        required_artifact = normalized_artifact
        if required_artifact == "monthly":
            table = "settlement_monthly_overlay"
            partition_column = "partition_key"
            tombstone_clause = "AND (tombstone = FALSE OR tombstone IS NULL)"
        elif required_artifact == "ranking":
            table = "settlement_ranking_overlay"
            partition_column = "partition_key"
            tombstone_clause = "AND (tombstone = FALSE OR tombstone IS NULL)"
        else:
            table = "store_score_snapshot_generation"
            partition_column = "partition_key"
            tombstone_clause = ""
        requirement_groups: dict[tuple[str, str], int] = {
            (data_generation_id, partition_key): int(
                by_generation_and_key[
                    (
                        resolutions[partition_key].nearest_manifest_owner_generation or "",
                        partition_key,
                    )
                ].get("row_count")
                or 0
            )
            for _, data_generation_id, partition_key in overlay_requirements
        }
        requirement_keys = list(requirement_groups)
        present: dict[tuple[str, str, str], int] = {}
        batch_size = 400
        for batch_index in range(0, len(requirement_keys), batch_size):
            batch = requirement_keys[batch_index : batch_index + batch_size]
            generation_values = sorted({generation for generation, _ in batch})
            partition_values = sorted({partition for _, partition in batch})
            generation_placeholders, generation_params = _manifest_params(
                f"presence_generation_{batch_index}", generation_values
            )
            partition_placeholders, partition_params = _manifest_params(
                f"presence_partition_{batch_index}", partition_values
            )
            presence_params: dict[str, str] = {
                "presence_artifact": required_artifact,
                **generation_params,
                **partition_params,
            }
            presence_sql = f"""
                SELECT :presence_artifact AS artifact,
                       generation_id,
                       {partition_column} AS partition_key,
                       COUNT(*) AS present_count
                FROM {table}
                WHERE generation_id IN ({generation_placeholders})
                  AND {partition_column} IN ({partition_placeholders})
                  {tombstone_clause}
                GROUP BY generation_id, {partition_column}
            """
            try:
                present_result = session.execute(text(presence_sql), presence_params)
                for row in present_result.mappings().all():
                    present[
                        (
                            _as_text(row.get("artifact")),
                            _as_text(row.get("generation_id")),
                            _as_text(row.get("partition_key")),
                        )
                    ] = int(row.get("present_count") or 0)
            except Exception as exc:
                raise LineageError("failed to validate overlay data rows") from exc
        missing = [
            (required_artifact, generation, partition)
            for generation, partition in requirement_keys
            if present.get((required_artifact, generation, partition), 0)
            < requirement_groups[(generation, partition)]
        ]
        if missing:
            raise LineageError("overlay ownership requires missing data rows")
    return resolutions


__all__ = [
    "LineageError",
    "ProjectionLineageError",
    "PartitionKey",
    "PartitionResolution",
    "active_generation_id",
    "canonical_score_partition_key",
    "resolve_projection_partitions",
]
