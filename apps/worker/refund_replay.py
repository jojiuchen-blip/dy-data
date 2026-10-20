"""Bounded replay of existing refund evidence, without settlement execution.

Preview performs SELECTs only. Apply revalidates every row under a lock and
records a separate repair JobRun. Ambiguous evidence and existing financial
projections require reconciliation, never an amount/scope override.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any, Iterator

from sqlalchemy import func, select, text as sql_text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DouyinRefundEvent, JobImpact, JobRun, RawDouyinOrder, RawDouyinOrderCoupon,
    RawDouyinRefundRecord, SettlementFeeAdjustment, SettlementFeeResult,
    SettlementFeeResultCurrent, SettlementStatementEntry,
)
from apps.api.dy_api.dashboard_publications.lifecycle import PublicationError
from apps.api.dy_api.dashboard_publications.sources import assert_sources_ready
from apps.worker.collectors import refunds
from apps.worker.collectors.normalizers import first, text
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY, finish_job_run, payload_fingerprint, start_job_run


class RefundReplayError(ValueError):
    """A replay request cannot be applied safely."""


@dataclass(frozen=True)
class ReplayBounds:
    """Explicit, finite replay window and database time limits."""

    source_run_id: str
    after_id: int
    batch_size: int
    max_batches: int
    statement_timeout_ms: int = 3000
    lock_timeout_ms: int = 500
    transaction_timeout_ms: int = 15000

    def __post_init__(self) -> None:
        if not isinstance(self.source_run_id, str) or not 1 <= len(self.source_run_id.strip()) <= 64:
            raise RefundReplayError("source_run_id is required (at most 64 characters)")
        for name, low, high in (
            ("after_id", 0, 2**63 - 1), ("batch_size", 1, 100), ("max_batches", 1, 20),
            ("statement_timeout_ms", 1, 5000), ("lock_timeout_ms", 1, 1000),
            ("transaction_timeout_ms", 1, 30000),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise RefundReplayError(f"{name} must be between {low} and {high}")
        if self.lock_timeout_ms > self.statement_timeout_ms or self.statement_timeout_ms > self.transaction_timeout_ms:
            raise RefundReplayError("timeouts must satisfy lock <= statement <= transaction")


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("bounded transaction deadline exceeded")


def _configure_transaction(session: Session, bounds: ReplayBounds, *, write: bool,
                           repair_run_id: str | None = None) -> None:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        if not write:
            session.execute(sql_text("SET TRANSACTION READ ONLY"))
        for name, value in (
            ("statement_timeout", bounds.statement_timeout_ms),
            ("lock_timeout", bounds.lock_timeout_ms),
            ("idle_in_transaction_session_timeout", bounds.transaction_timeout_ms),
        ):
            session.execute(sql_text("SELECT set_config(:name, :value, true)"),
                            {"name": name, "value": str(value)})
        if session.get_bind().dialect.server_version_info >= (17,):
            session.execute(sql_text("SELECT set_config('transaction_timeout', :value, true)"),
                            {"value": str(bounds.transaction_timeout_ms)})
        if write:
            # Match normal heavy-job claiming: claim mutex -> writer-state
            # check -> financial SHARE -> raw row locks. Never infer that an
            # expired lease means a running writer has stopped.
            if not session.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY))):
                raise RefundReplayError("heavy_sync_claim_lock_busy")
            try:
                assert_sources_ready(session, exclude_repair_run_id=repair_run_id)
            except PublicationError as exc:
                raise RefundReplayError("source_jobs_or_repairs_not_ready") from exc
            session.execute(sql_text(
                "LOCK TABLE settlement_fee_result, settlement_fee_result_current, "
                "settlement_fee_adjustment, settlement_statement_entry IN SHARE MODE"
            ))
    elif dialect == "sqlite":
        # Local tests use a database-wide write reservation in lieu of row locks.
        session.connection().exec_driver_sql(f"PRAGMA busy_timeout={bounds.lock_timeout_ms}")
        if write:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    else:
        raise RefundReplayError("only PostgreSQL and local SQLite are supported")


@contextmanager
def _transaction(engine: Engine, bounds: ReplayBounds, *, write: bool,
                 repair_run_id: str | None = None) -> Iterator[tuple[Session, float]]:
    deadline = time.monotonic() + bounds.transaction_timeout_ms / 1000
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        with session.begin():
            _configure_transaction(session, bounds, write=write, repair_run_id=repair_run_id)
            yield session, deadline
            _check_deadline(deadline)


def _utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _has_financial_projection(session: Session, raw: RawDouyinRefundRecord, coupon_ids: list[str]) -> bool:
    # Separate predicates avoid OR + hashed-subplan scans. Historical order
    # equality probes remain statement-timeout bounded: these tables do not
    # currently all have a leading order_id index. Coupon probes use existing
    # leading coupon indexes and at most 100 keys.
    for model in (SettlementFeeResult, SettlementFeeAdjustment, SettlementStatementEntry):
        if session.scalar(select(model.id).where(model.order_id == raw.order_id).limit(1)) is not None:
            return True
    if coupon_ids:
        for model in (SettlementFeeResult, SettlementFeeAdjustment, SettlementStatementEntry, SettlementFeeResultCurrent):
            if session.scalar(select(model.id).where(model.coupon_id.in_(coupon_ids)).limit(1)) is not None:
                return True
    return False


def _inspect_row(session: Session, raw: RawDouyinRefundRecord) -> dict[str, Any]:
    reasons: list[str] = []
    payload = raw.raw_payload
    event = session.scalar(select(DouyinRefundEvent).where(
        DouyinRefundEvent.refund_event_id == raw.source_record_key,
    ))
    result = {"raw_id": raw.id, "payload_hash": raw.payload_hash,
              "existing_event_id": event.id if event else None, "status": "blocked", "reasons": reasons,
              "financial_check": "not_checked_blocked_evidence"}
    if not isinstance(payload, dict) or payload_fingerprint(payload) != raw.payload_hash:
        reasons.append("payload_hash_mismatch")
        return result
    stable_id = refunds._stable_refund_id(payload)
    order_id = text(first(payload, "order_id", "order.order_id", "trade_order_id"))
    status_value = text(first(payload, "refund_status", "status", "after_sale_status", "state"))
    status = refunds.REFUND_STATUS_MAP.get((status_value or "").strip().lower(), 0)
    amount, conflict, invalid, ambiguous = refunds._refund_amount(payload)
    scope = refunds._refund_type(payload)
    occurred_at = refunds._business_occurred_at(payload, status)
    if stable_id != raw.source_record_key or raw.refund_id not in (None, stable_id):
        reasons.append("refund_identity_mismatch")
    if not order_id or order_id != raw.order_id:
        reasons.append("order_identity_mismatch")
    if status == 0 or status != raw.normalized_refund_status or status_value != raw.raw_refund_status:
        reasons.append("status_missing_unknown_or_mismatch")
    if ambiguous:
        reasons.append("refund_amount_unit_ambiguous")
    elif invalid or conflict or amount is None:
        reasons.append("refund_amount_invalid_conflicting_or_missing")
    elif raw.refund_amount_cent is not None and raw.refund_amount_cent != amount:
        reasons.append("refund_amount_snapshot_mismatch")
    if scope not in (1, 2):
        reasons.append("refund_scope_not_explicit")
    observed_at = raw.source_observed_at or refunds._observation_time(payload)
    if occurred_at is None or observed_at is None:
        reasons.append("business_or_observation_time_missing")
    cached_time = raw.refund_applied_at if status == 1 else raw.refund_completed_at if status == 2 else None
    if cached_time and _utc(cached_time) != _utc(occurred_at):
        reasons.append("business_time_snapshot_mismatch")
    if raw.refund_applied_at and raw.refund_completed_at and _utc(raw.refund_applied_at) > _utc(raw.refund_completed_at):
        reasons.append("business_time_order_invalid")
    if session.scalar(select(RawDouyinOrder.id).where(RawDouyinOrder.order_id == raw.order_id).limit(1)) is None:
        reasons.append("order_evidence_missing")
    coupon_id, coupon_ambiguous = refunds._resolve_coupon(session, payload, raw.order_id)
    if coupon_ambiguous or (scope == 1 and coupon_id is None):
        reasons.append("coupon_scope_ambiguous")
    if coupon_id:
        coupon_order = session.scalar(select(RawDouyinOrderCoupon.order_id).where(RawDouyinOrderCoupon.coupon_id == coupon_id))
        if coupon_order != raw.order_id:
            reasons.append("coupon_missing_or_order_mismatch")
    if event is not None:
        if (event.payload_fingerprint != raw.payload_hash or event.order_id != raw.order_id
                or event.coupon_id != coupon_id or event.refund_status != status
                or event.refund_type != scope or event.refund_amount_cent != amount
                or _utc(event.occurred_at) != _utc(occurred_at)):
            # Existing different observations require a separate reconciliation;
            # this tool cannot turn an old raw snapshot into a newer observation.
            reasons.append("existing_event_requires_reconciliation")
    if not reasons:
        coupon_ids = list(session.scalars(select(RawDouyinOrderCoupon.coupon_id).where(
            RawDouyinOrderCoupon.order_id == raw.order_id,
        ).limit(101)))
        if len(coupon_ids) > 100:
            result["financial_check"] = "not_checked_scope_too_large"
            reasons.append("financial_scope_too_large")
        else:
            result["financial_check"] = "checked"
            if _has_financial_projection(session, raw, coupon_ids):
                reasons.append("existing_financial_projection_requires_reconciliation")
    result["status"] = "blocked" if reasons else "ready"
    return result


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def preview_refunds(engine: Engine, bounds: ReplayBounds, *, upper_id: int | None = None) -> dict[str, Any]:
    """Read at most batch_size * max_batches rows, freezing the PK upper bound."""
    if upper_id is not None and (type(upper_id) is not int or not bounds.after_id <= upper_id <= 2**63 - 1):
        raise RefundReplayError("upper_id must be a finite integer at least after_id")
    rows: list[dict[str, Any]] = []
    cursor = bounds.after_id
    for _ in range(bounds.max_batches):
        with _transaction(engine, bounds, write=False) as (session, deadline):
            if upper_id is None:
                upper_id = max(cursor, session.scalar(select(func.max(RawDouyinRefundRecord.id)).where(
                    RawDouyinRefundRecord.source_run_id == bounds.source_run_id,
                )) or 0)
            batch = list(session.scalars(select(RawDouyinRefundRecord).where(
                RawDouyinRefundRecord.source_run_id == bounds.source_run_id,
                RawDouyinRefundRecord.id > cursor, RawDouyinRefundRecord.id <= upper_id,
            ).order_by(RawDouyinRefundRecord.id).limit(bounds.batch_size)))
            for raw in batch:
                _check_deadline(deadline)
                rows.append(_inspect_row(session, raw))
                cursor = raw.id
        if len(batch) < bounds.batch_size:
            break
    with _transaction(engine, bounds, write=False) as (session, _):
        has_more = session.scalar(select(RawDouyinRefundRecord.id).where(
            RawDouyinRefundRecord.source_run_id == bounds.source_run_id,
            RawDouyinRefundRecord.id > cursor, RawDouyinRefundRecord.id <= upper_id,
        ).limit(1)) is not None
    ready = sum(row["status"] == "ready" for row in rows)
    report = {"schema_version": 1, "mode": "preview", "bounds": asdict(bounds),
              "upper_id": upper_id, "cursor": cursor, "has_more": has_more,
              "scanned": len(rows), "ready": ready, "blocked": len(rows) - ready,
              "existing_events": sum(row["existing_event_id"] is not None for row in rows),
              "financial_guard": {"policy": "only_otherwise_ready", "not_checked_is_not_approval": True,
                  "checked": sum(row["financial_check"] == "checked" for row in rows),
                  "not_checked": sum(row["financial_check"] != "checked" for row in rows)},
              "reasons": dict(Counter(reason for row in rows for reason in row["reasons"])), "rows": rows}
    return {**report, "preview_digest": _digest(report)}


def _validate_preview(preview: dict[str, Any], expected_digest: str) -> ReplayBounds:
    if not isinstance(preview, dict):
        raise RefundReplayError("preview must be a JSON object")
    document = {key: value for key, value in preview.items() if key != "preview_digest"}
    if preview.get("preview_digest") != expected_digest or _digest(document) != expected_digest:
        raise RefundReplayError("preview digest mismatch")
    if preview.get("schema_version") != 1 or preview.get("mode") != "preview":
        raise RefundReplayError("unsupported preview format")
    bounds = ReplayBounds(**preview["bounds"])
    rows = preview["rows"]
    if (not isinstance(rows, list) or type(preview["upper_id"]) is not int
            or not bounds.after_id <= preview["upper_id"] <= 2**63 - 1):
        raise RefundReplayError("preview upper bound or rows are invalid")
    ids = [row["raw_id"] for row in rows]
    if (len(rows) > bounds.batch_size * bounds.max_batches or any(type(value) is not int for value in ids)
            or ids != sorted(set(ids)) or any(not bounds.after_id < value <= preview["upper_id"] for value in ids)
            or preview["cursor"] != (ids[-1] if ids else bounds.after_id)):
        raise RefundReplayError("preview row bounds are invalid")
    if any(row["status"] not in ("ready", "blocked") for row in rows):
        raise RefundReplayError("preview row status is invalid")
    ready = sum(row["status"] == "ready" for row in rows)
    if preview["scanned"] != len(rows) or preview["ready"] != ready or preview["blocked"] != len(rows) - ready:
        raise RefundReplayError("preview counts are invalid")
    return bounds


def _summarize_apply(report: dict[str, Any]) -> None:
    for status, field in (("applied", "applied"), ("unchanged", "unchanged"), ("blocked", "blocked")):
        report[field] = sum(row["status"] == status for row in report["rows"])
    report["reasons"] = dict(Counter(reason for row in report["rows"] for reason in row["reasons"]))


def _impact_summary(session: Session, repair_run_id: str) -> dict[str, Any]:
    count, lower, upper = session.execute(select(
        func.count(JobImpact.id), func.min(JobImpact.id), func.max(JobImpact.id),
    ).where(JobImpact.source_run_id == repair_run_id)).one()
    return {"job_impacts": count, "impact_min_id": lower, "impact_max_id": upper}


def apply_refunds(engine: Engine, preview: dict[str, Any], *, expected_digest: str,
                  repair_run_id: str, reason: str) -> dict[str, Any]:
    """Apply only reviewed ready rows, with a durable separate repair audit.

    Completed repair IDs return their prior result. Interrupted repair IDs are
    refused; a new preview and repair ID are required to inspect committed work.
    """
    bounds = _validate_preview(preview, expected_digest)
    if (not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000
            or not isinstance(repair_run_id, str) or not 1 <= len(repair_run_id.strip()) <= 64
            or repair_run_id == bounds.source_run_id):
        raise RefundReplayError("apply requires reason and a separate repair_run_id")
    report: dict[str, Any] = {"mode": "apply", "repair_run_id": repair_run_id,
        "preview_digest": expected_digest, "scanned": preview["scanned"],
        "applied": 0, "unchanged": 0, "blocked": 0, "rows": [],
        "cursor": bounds.after_id, "upper_id": preview["upper_id"],
        "needs_downstream_processing": False, "job_impacts": 0, "audit_finalized": False}
    audit = {"source_run_id": bounds.source_run_id, "reason": reason,
             "preview_digest": expected_digest, "bounds": asdict(bounds), "upper_id": preview["upper_id"],
             "needs_downstream_processing": False}
    with _transaction(engine, bounds, write=True, repair_run_id=repair_run_id) as (session, _):
        existing = session.get(JobRun, repair_run_id)
        if existing is not None:
            metadata = existing.metadata_json or {}
            if (existing.job_name != "refund_evidence_replay" or metadata.get("preview_digest") != expected_digest
                    or metadata.get("reason") != reason or "result" not in metadata
                    or existing.status not in ("success", "partial", "failed")):
                raise RefundReplayError("repair_run_id is already used or interrupted")
            return metadata["result"]
        start_job_run(session, repair_run_id, "refund_evidence_replay", metadata_json=audit)
    for offset in range(0, len(preview["rows"]), bounds.batch_size):
        batch = preview["rows"][offset:offset + bounds.batch_size]
        outcomes: list[dict[str, Any]] = []
        try:
            with _transaction(engine, bounds, write=True, repair_run_id=repair_run_id) as (session, deadline):
                for expected in batch:
                    _check_deadline(deadline)
                    outcome = {**expected, "status": "blocked", "reasons": list(expected["reasons"])}
                    outcomes.append(outcome)
                    if expected["status"] != "ready":
                        continue
                    raw = session.scalar(select(RawDouyinRefundRecord).where(
                        RawDouyinRefundRecord.id == expected["raw_id"],
                        RawDouyinRefundRecord.source_run_id == bounds.source_run_id,
                    ).with_for_update().execution_options(populate_existing=True))
                    if raw is None or raw.payload_hash != expected["payload_hash"] or payload_fingerprint(raw.raw_payload) != expected["payload_hash"]:
                        outcome["reasons"] = ["snapshot_changed_since_preview"]
                        continue
                    fresh = _inspect_row(session, raw)
                    outcome["financial_check"] = fresh["financial_check"]
                    if fresh["status"] != "ready":
                        outcome["reasons"] = fresh["reasons"]
                        continue
                    if fresh["existing_event_id"] is not None:
                        outcome.update(status="unchanged", existing_event_id=fresh["existing_event_id"], reasons=[])
                        continue
                    provenance = (deepcopy(raw.raw_payload), raw.payload_hash, raw.source_run_id)
                    with session.begin_nested():
                        if not refunds._process_refund(session, deepcopy(raw.raw_payload), source_run_id=repair_run_id):
                            raise RefundReplayError("collector_rejected_evidence")
                        session.flush()
                        if provenance != (raw.raw_payload, raw.payload_hash, raw.source_run_id):
                            raise RefundReplayError("raw_provenance_changed")
                    outcome.update(status="applied", reasons=[])
                _check_deadline(deadline)
                pending = deepcopy(report)
                pending["rows"].extend(outcomes)
                pending["cursor"] = batch[-1]["raw_id"]
                _summarize_apply(pending)
                pending.update(_impact_summary(session, repair_run_id))
                pending["needs_downstream_processing"] = pending["needs_downstream_processing"] or pending["job_impacts"] > 0
                job = session.get(JobRun, repair_run_id)
                job.metadata_json = {**audit, "progress": pending,
                    "needs_downstream_processing": pending["needs_downstream_processing"]}
                job.success_count = pending["applied"] + pending["unchanged"]
                job.failed_count = pending["blocked"]
            report = pending
        except (SQLAlchemyError, TimeoutError, RefundReplayError) as exc:
            # The entire bounded batch rolled back. Never report its rows applied.
            code = str(exc) if isinstance(exc, RefundReplayError) else "transaction_timeout_or_database_error"
            guard_blocked = code in {"heavy_sync_claim_lock_busy", "source_jobs_or_repairs_not_ready"}
            remaining = preview["rows"][offset:] if guard_blocked else batch
            report["rows"].extend({**row, "status": "blocked", "reasons": [code]} for row in remaining)
            report["cursor"] = remaining[-1]["raw_id"]
            if guard_blocked:
                break
    _summarize_apply(report)
    report["status"] = "partial" if report["blocked"] and report["applied"] + report["unchanged"] else "failed" if report["blocked"] else "success"
    try:
        with _transaction(engine, bounds, write=True, repair_run_id=repair_run_id) as (session, _):
            report.update(_impact_summary(session, repair_run_id))
            report["needs_downstream_processing"] = report["needs_downstream_processing"] or report["job_impacts"] > 0
            report["audit_finalized"] = True
            job = session.get(JobRun, repair_run_id)
            job.metadata_json = {**audit, "result": report,
                "needs_downstream_processing": report["needs_downstream_processing"]}
            finish_job_run(session, repair_run_id, status=report["status"],
                           success_count=report["applied"] + report["unchanged"], failed_count=report["blocked"])
    except (RefundReplayError, SQLAlchemyError, TimeoutError):
        # Do not bypass the claim/source fence just to finish the audit. The
        # last committed progress and its sticky downstream flag remain durable.
        report["audit_finalized"] = False
        report["status"] = "partial" if report["applied"] + report["unchanged"] else "failed"
        report["audit_error"] = "audit_finish_guard_or_database_blocked"
    return report
