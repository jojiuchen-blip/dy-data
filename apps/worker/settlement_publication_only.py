"""Reviewed publication of existing fee facts; never materialize or repair fees."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from datetime import timedelta
import hashlib
import json
import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    DimStore, FinanceOperationAudit, InvoiceRecord, JobRun, PromotionInvoiceAllocation,
    SettlementDispute, SettlementProjectionActive, SettlementStatement,
    SettlementStatementConfirmation,
)
from apps.worker.billing_source_capture import BillingSourceDriftError, _payload, collect_billing_sources
from apps.worker.protected_billing_authority import is_protected_statement
from apps.worker.settlement import (
    FORMAL_SETTLEMENT_START, SettlementStats, _sparse_base_chain,
    _sparse_expand_affected_months, _sparse_month,
)

PROTOCOL = "dydata-settlement-publication-only-v1"
MODE_KEY = "publication_only"


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _dependency_snapshot(session: Session, bills: Sequence[SettlementStatement]) -> list:
    """Bind financial state without loading file bodies or private ticket payloads."""
    dependencies = []
    for bill in bills:
        checks = (
            select(SettlementStatementConfirmation.confirmation_id, SettlementStatementConfirmation.fee_direction,
                   SettlementStatementConfirmation.confirmation_status, SettlementStatementConfirmation.confirmed_amount_cent,
                   SettlementStatementConfirmation.confirmed_at).where(SettlementStatementConfirmation.statement_id == bill.statement_id),
            select(InvoiceRecord.invoice_id, InvoiceRecord.version_no, InvoiceRecord.is_current,
                   InvoiceRecord.is_tombstone, InvoiceRecord.invoice_status).where(
                       InvoiceRecord.store_id == bill.store_id, InvoiceRecord.statement_month == bill.statement_month),
            select(PromotionInvoiceAllocation.allocation_id, PromotionInvoiceAllocation.invoice_id,
                   PromotionInvoiceAllocation.is_current, PromotionInvoiceAllocation.allocated_amount_cent).where(
                       PromotionInvoiceAllocation.store_id == bill.store_id, PromotionInvoiceAllocation.statement_month == bill.statement_month),
            select(SettlementDispute.dispute_id, SettlementDispute.status, SettlementDispute.result_statement_id).where(
                SettlementDispute.store_id == bill.store_id, SettlementDispute.statement_month == bill.statement_month),
        )
        dependencies.append([bill.statement_id, [sorted((tuple(row) for row in session.execute(query)), key=str) for query in checks]])
    return dependencies


def _preview(session: Session, months: Sequence[str]) -> dict:
    from apps.worker.settlement_rebuild import _lock_billing_publication_base, SettlementMonthLockedError

    requested = tuple(sorted({_sparse_month(month, label="requested month") for month in months}))
    if not requested or min(requested) < FORMAL_SETTLEMENT_START.strftime("%Y-%m"):
        raise ValueError("publication requires explicit formal settlement months")
    active = session.get(SettlementProjectionActive, "settlement", populate_existing=True)
    if active is None or not active.generation_id:
        raise ValueError("publication requires an active published settlement base")
    base_id = active.generation_id
    _lock_billing_publication_base(session, base_id)
    _sparse_base_chain(session, base_id)
    closure = _sparse_expand_affected_months(session, requested)
    locked = session.scalar(select(SettlementStatement.statement_id).where(
        SettlementStatement.statement_month.in_(closure), SettlementStatement.statement_status == 4,
    ).limit(1))
    if locked:
        raise SettlementMonthLockedError("publication-only currently refuses locked month closure")
    bills = list(session.scalars(select(SettlementStatement).where(
        SettlementStatement.is_current.is_(True), SettlementStatement.statement_month.in_(closure),
    ).order_by(SettlementStatement.store_id, SettlementStatement.statement_month).execution_options(populate_existing=True)))
    sources = collect_billing_sources(session, months=closure, slots=[(bill.store_id, bill.statement_month) for bill in bills])
    if _sparse_expand_affected_months(session, requested) != closure:
        raise BillingSourceDriftError("publication month closure changed during preview")
    # A bill version may have committed while capture waited for its slot.
    bills = list(session.scalars(select(SettlementStatement).where(
        SettlementStatement.is_current.is_(True), SettlementStatement.statement_month.in_(closure),
    ).order_by(SettlementStatement.store_id, SettlementStatement.statement_month).execution_options(populate_existing=True)))
    by_slot = {(bill.store_id, bill.statement_month): bill for bill in bills}
    grouped = defaultdict(list)
    for slot in by_slot:
        grouped[slot] = []
    for source in sources:
        grouped[(source.store_id, source.posting_month)].append(source)
    headers, bill_facts = [], []
    money_fields = tuple(f"{direction}_{kind}_fee_cent" for direction in ("promotion", "management") for kind in ("original", "adjustment", "net"))
    for (store_id, month), rows in sorted(grouped.items()):
        bill = by_slot.get((store_id, month))
        if bill is None and session.scalar(select(SettlementStatement.id).where(
            SettlementStatement.store_id == store_id, SettlementStatement.statement_month == month,
        ).limit(1)) is not None:
            raise ValueError("publication has historical bills without a current version")
        if bill is None and session.get(DimStore, store_id) is None:
            raise ValueError("publication source has no responsible store")
        protected = bill is not None and is_protected_statement(session, bill)
        header = {"store_id": store_id, "month": month, "source_count": len(rows),
                  "current_statement_id": bill.statement_id if bill else None,
                  "current_version": bill.version_no if bill else None, "protected": protected}
        for direction, prefix in ((1, "promotion"), (2, "management")):
            original = sum(row.fee_amount_cent for row in rows if row.fee_direction == direction and row.source_type == 1)
            adjustment = sum(row.fee_amount_cent for row in rows if row.fee_direction == direction and row.source_type == 2)
            header.update({f"{prefix}_original_fee_cent": original, f"{prefix}_adjustment_fee_cent": adjustment,
                           f"{prefix}_net_fee_cent": original + adjustment})
        payload_hash = _hash([asdict(row) for row in sorted(rows, key=lambda row: (row.source_type, row.source_record_id))])
        unchanged = bill is not None and session.scalar(select(FinanceOperationAudit.id).where(
            FinanceOperationAudit.target_id == bill.statement_id,
            FinanceOperationAudit.operation_type == "GENERATE_PENDING_STATEMENT",
            FinanceOperationAudit.request_payload_sha256 == payload_hash,
        ).limit(1)) is not None
        action = "protected" if protected else "unchanged" if unchanged else "version" if bill else "create"
        header.update(action=action, expected_version=bill.version_no if action in ("protected", "unchanged") else bill.version_no + 1 if bill else 1)
        headers.append(header)
        if bill:
            bill_facts.append({"statement_id": bill.statement_id, "store_id": store_id, "month": month,
                               "version": bill.version_no, "status": bill.statement_status, "protected": protected,
                               "confirmed_at": bill.confirmed_at, "locked_at": bill.locked_at, "lock_version": bill.lock_version,
                               "store_name_snapshot": bill.store_name_snapshot, "sap_code_snapshot": bill.sap_code_snapshot,
                               **{field: getattr(bill, field) for field in money_fields}})
    result = {"protocol": PROTOCOL, "base_generation_id": base_id, "requested_months": list(requested),
              "closure_months": list(closure), "source_count": len(sources), "expected_headers": headers,
              "will_version_unprotected": [row for row in headers if row["action"] in ("create", "version")]}
    result["preview_hash"] = _hash({**result, "sources": _payload(sources), "bills": bill_facts,
                                    "dependencies": _dependency_snapshot(session, bills)})
    return result


def preview_settlement_publication(factory: sessionmaker, *, months: Sequence[str]) -> dict:
    """Read-only, full-month preview; closing the session releases all read locks."""
    with factory() as session:
        return _preview(session, months)


def _verify_preview(session: Session, months: Sequence[str], expected_hash: str) -> dict:
    preview = _preview(session, months)
    if preview["preview_hash"] != expected_hash:
        raise BillingSourceDriftError("publication preview changed; create and review a new dry-run")
    return preview


def apply_settlement_publication(factory: sessionmaker, *, months: Sequence[str], preview_hash: str,
                                 lease_duration: timedelta = timedelta(minutes=15)) -> dict:
    """Admit and claim atomically, then publish without invoking fee rebuilds."""
    from apps.worker import settlement_rebuild as rebuild

    if not isinstance(preview_hash, str) or re.fullmatch("[0-9a-f]{64}", preview_hash) is None:
        raise ValueError("apply requires the exact dry-run preview hash")
    if lease_duration <= timedelta(0):
        raise ValueError("lease_duration must be positive")
    months = tuple(months)
    job_id = "settlement-publication-only-" + uuid4().hex
    with rebuild._settlement_rebuild_claim_transaction(factory) as session:
        if session is None:
            raise RuntimeError("heavy publication claim is unavailable")
        job = JobRun(job_id=job_id, job_name=rebuild.SETTLEMENT_REBUILD_JOB_NAME, status="queued",
                     max_attempts=1, metadata_json={MODE_KEY: {"protocol": PROTOCOL, "requested_months": list(months), "preview_hash": preview_hash}})
        session.add(job)
        session.flush()
        claim_id = rebuild._claim_settlement_rebuild_in_session(session, job_id=job_id,
            claim_time=rebuild._database_utcnow(session), lease_duration=lease_duration)
        if not claim_id:
            raise RuntimeError("heavy publication resource/claim admission refused")
        _verify_preview(session, months, preview_hash)
    run_settlement_publication_job(factory, job_id=job_id, claim_id=claim_id, lease_duration=lease_duration)
    with factory() as session:
        job = session.get(JobRun, job_id)
        return {"protocol": PROTOCOL, "job_id": job_id, "status": job.status,
                "projection": job.metadata_json.get("settlement_projection"), "billing": job.metadata_json.get("billing_generation")}


def run_settlement_publication_job(factory: sessionmaker, *, job_id: str, claim_id: str | None = None,
        lease_duration: timedelta = timedelta(minutes=15), heartbeat_interval_seconds: float | None = None) -> bool:
    """Recovery dispatch stays on the publication path and revalidates review."""
    from apps.worker import settlement_rebuild as rebuild

    with factory() as session:
        job = session.get(JobRun, job_id)
        mode = (job.metadata_json or {}).get(MODE_KEY) if job else None
    if not isinstance(mode, dict) or mode.get("protocol") != PROTOCOL:
        raise ValueError("reviewed publication job metadata is missing")
    if claim_id is None:
        claim_id = rebuild.claim_settlement_rebuild_job(factory, job_id=job_id, lease_duration=lease_duration)
    if not claim_id:
        return False
    months, expected = tuple(mode["requested_months"]), mode["preview_hash"]
    def source_guard(session: Session) -> None:
        _verify_preview(session, months, expected)
    try:
        with rebuild._settlement_rebuild_heartbeat_watchdog(factory, job_id=job_id, claim_id=claim_id,
                lease_duration=lease_duration, heartbeat_interval_seconds=heartbeat_interval_seconds) as progress:
            rebuild.refresh_active_settlement_lineage(factory, job_id=job_id, claim_id=claim_id,
                months=months, lease_duration=lease_duration, progress_callback=progress,
                source_guard=source_guard)
        rebuild._finish_claimed_settlement_rebuild(factory, job_id=job_id, claim_id=claim_id,
                                                  stats=SettlementStats(0, 0, 0, 0))
    except rebuild.SettlementRebuildLeaseLost:
        raise
    except Exception as exc:
        transition = rebuild._fail_claimed_settlement_rebuild(factory, job_id=job_id, claim_id=claim_id,
            error_message=str(exc), requires_new_job=True)
        if transition == "reconciled":
            return True
        raise
    return True
