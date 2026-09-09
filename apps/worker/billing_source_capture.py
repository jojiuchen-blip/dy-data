"""Persist private billing sources before publishing aggregate projections."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    JobEvent, SettlementBillingSourceBundle, SettlementFeeAdjustment,
    SettlementFeeResult, utcnow,
)
from apps.worker.settlement import (
    StatementSource, _adjustment_statement_source, _lock_settlement_slot,
    _result_statement_source, _sparse_authority_relation, _stable_business_id,
)


class BillingSourceDriftError(ValueError):
    """Frozen inputs changed; only a new rebuild job may capture new inputs."""


def collect_billing_sources(
    session: Session, *, months: Sequence[str], slots: Sequence[tuple[str, str]] = (),
) -> list[StatementSource]:
    """Capture the same source identities as the sparse aggregation under slot locks."""
    if not months:
        return []
    relation = _sparse_authority_relation(tuple(months))
    query = select(
        relation.c.source_kind, relation.c.source_id, relation.c.store_id, relation.c.month,
    ).distinct().order_by(relation.c.store_id, relation.c.month, relation.c.source_kind, relation.c.source_id)
    references = session.execute(query).all()
    locked_slots = {(store, month) for store, month in slots} | {(row.store_id, row.month) for row in references}
    for store_id, month in sorted(locked_slots):
        if not store_id:
            raise ValueError("billing source has no responsible store")
        _lock_settlement_slot(session, store_id, month)
    # A writer may have committed while we waited for a slot. Never freeze its
    # superseded references. New slots require a fresh transaction/lock order.
    references = session.execute(query).all()
    if any((row.store_id, row.month) not in locked_slots for row in references):
        raise ValueError("billing source slots changed during capture; retry in a new transaction")
    sources = []
    for reference in references:
        if reference.source_kind == "result":
            result = session.scalar(select(SettlementFeeResult).where(
                SettlementFeeResult.fee_result_id == reference.source_id,
            ))
            if result is None:
                raise ValueError("billing result disappeared during capture")
            sources.append(_result_statement_source(session, result))
        else:
            adjustment = session.scalar(select(SettlementFeeAdjustment).where(
                SettlementFeeAdjustment.adjustment_id == reference.source_id,
            ))
            if adjustment is None:
                raise ValueError("billing adjustment disappeared during capture")
            result = session.scalar(select(SettlementFeeResult).where(
                SettlementFeeResult.fee_result_id == adjustment.original_fee_result_id,
            ))
            if result is None:
                raise ValueError("billing adjustment original is missing")
            sources.append(_adjustment_statement_source(session, adjustment, result))
    return sources


def _payload(sources: Sequence[StatementSource]) -> list[dict]:
    return json.loads(json.dumps(
        [asdict(row) for row in sorted(sources, key=lambda row: (row.store_id, row.posting_month, row.source_type, row.source_record_id))],
        default=str, sort_keys=True, separators=(",", ":"),
    ))


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _marker(session: Session, generation_id: str, job_id: str) -> JobEvent | None:
    return session.get(JobEvent, _stable_business_id("billing-source-manifest", job_id, generation_id))


def freeze_billing_sources(
    session: Session, *, generation_id: str, job_id: str, sources: Sequence[StatementSource],
    slots: Sequence[tuple[str, str]] = (),
) -> str:
    """Append one bundle per store/month and a data-free completion marker.

    The caller must serialize source writers while capturing and validating.
    Retries may reuse exactly the same input, never replace the frozen input.
    """
    payload = _payload(sources)
    all_slots = sorted({(store_id, month) for store_id, month in slots}
                       | {(row["store_id"], row["posting_month"]) for row in payload})
    fingerprint = _fingerprint({"sources": payload, "slots": all_slots})
    marker = _marker(session, generation_id, job_id)
    if marker is not None:
        if marker.payload_json.get("fingerprint") != fingerprint:
            raise BillingSourceDriftError("billing sources changed after capture; create a new settlement rebuild job")
        load_billing_sources(session, generation_id=generation_id, job_id=job_id)
        return fingerprint
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for slot in all_slots:
        grouped[slot] = []
    seen = set()
    for row in payload:
        identity = (row["source_type"], row["source_record_id"])
        if identity in seen:
            raise ValueError("duplicate billing source identity")
        seen.add(identity)
        grouped[(row["store_id"], row["posting_month"])].append(row)
    for (store_id, month), rows in grouped.items():
        session.add(SettlementBillingSourceBundle(
            generation_id=generation_id, store_id=store_id, statement_month=month,
            source_job_id=job_id, source_fingerprint=_fingerprint(rows), sources_json=rows,
        ))
    session.add(JobEvent(
        event_id=_stable_business_id("billing-source-manifest", job_id, generation_id),
        job_id=job_id, event_type="settlement_billing_sources_frozen", actor_type="worker",
        idempotency_key=_stable_business_id("billing-source-manifest", generation_id),
        payload_json={"generation_id": generation_id, "fingerprint": fingerprint,
                      "source_count": len(payload), "bundle_count": len(grouped)},
        occurred_at=utcnow(),
    ))
    session.flush()
    return fingerprint


def load_billing_sources(session: Session, *, generation_id: str, job_id: str) -> list[StatementSource]:
    """Load only captured data; missing input is not an empty settlement."""
    marker = _marker(session, generation_id, job_id)
    if marker is None:
        raise ValueError("frozen billing source manifest is missing")
    bundles = list(session.scalars(select(SettlementBillingSourceBundle).where(
        SettlementBillingSourceBundle.generation_id == generation_id,
        SettlementBillingSourceBundle.source_job_id == job_id,
    ).order_by(SettlementBillingSourceBundle.store_id, SettlementBillingSourceBundle.statement_month)))
    payload = []
    for bundle in bundles:
        if _fingerprint(bundle.sources_json) != bundle.source_fingerprint:
            raise ValueError("frozen billing source bundle changed")
        payload.extend(bundle.sources_json)
    if (len(bundles) != marker.payload_json.get("bundle_count")
            or len(payload) != marker.payload_json.get("source_count")
            or _fingerprint({"sources": payload, "slots": [(row.store_id, row.statement_month) for row in bundles]}) != marker.payload_json.get("fingerprint")):
        raise ValueError("frozen billing source manifest changed")
    sources = []
    for raw in payload:
        row = dict(raw)
        for field in ("sale_time", "verify_time", "refund_at"):
            if row.get(field) is not None:
                row[field] = datetime.fromisoformat(row[field])
        if row.get("fee_rate") is not None:
            row["fee_rate"] = Decimal(row["fee_rate"])
        sources.append(StatementSource(**row))
    return sources


def load_billing_slots(session: Session, *, generation_id: str, job_id: str) -> list[tuple[str, str]]:
    """Include captured empty slots so revoked fees can produce a zero new version."""
    return [tuple(row) for row in session.execute(select(
        SettlementBillingSourceBundle.store_id, SettlementBillingSourceBundle.statement_month,
    ).where(
        SettlementBillingSourceBundle.generation_id == generation_id,
        SettlementBillingSourceBundle.source_job_id == job_id,
    ).order_by(SettlementBillingSourceBundle.store_id, SettlementBillingSourceBundle.statement_month))]
