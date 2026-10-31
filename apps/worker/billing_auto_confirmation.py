"""Reviewable, bounded compensation for overdue direction confirmations.

The scheduler is opt-in at rollout. A dry-run is never permission to confirm a
different version: apply re-reads the same batch under the publication/slot/row
locks and requires its exact hash. Explicit review holds are append-only finance
audits, not collection-quality errors, and are never cleared by rebuilding.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
import time
from uuid import uuid4

from sqlalchemy import event, func, select, text, tuple_
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    FinanceOperationAudit, InvoiceRecord, JobRun, PromotionInvoiceAllocation,
    SettlementDispute, SettlementMonthlyOverlay, SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementStatement, SettlementStatementConfirmation, SettlementStatementEntry,
)
from apps.worker.month_close import published_days_revisions, require_current_month_qualification
from apps.worker.account_qualification import AccountQualificationError
from apps.worker.priority_scheduler import _live_heavy_job
from apps.worker.projection_lineage import LineageError, resolve_projection_partitions
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY
from apps.worker.settlement import _lock_settlement_slot, _sparse_authority_relation
from src.dy_data.billing_dates import confirmation_due_at
from src.dy_data.billing_amounts import statement_confirmable_amounts

PROTOCOL = "billing-auto-confirmation-v1"
HOLD_OPERATION = "BILLING_CONFIRMATION_HOLD"
HOLD_TARGET = "BILLING_CONFIRMATION_SLOT"
LOGGER = logging.getLogger(__name__)
MAX_BATCH_SOURCE_ROWS = 50000
TRANSACTION_WALL_SECONDS = 30
STATEMENT_TIMEOUT_MS = 5000
_DEADLINE_KEY = "billing_confirmation_deadline"
_wall_clock = time.monotonic


class AutoConfirmationConflict(ValueError):
    """The reviewed financial state changed or is not safe to confirm."""


def auto_confirmation_enabled() -> bool:
    """Read the explicit rollout switch; an unset setting never writes bills."""
    return os.getenv("BILLING_AUTO_CONFIRM_ENABLED", "false").strip().lower() in ("true", "1", "yes", "on")


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _hold_target(store_id: str, month: str, direction: int) -> str:
    return "billing-slot-" + _hash([store_id, month, direction])[:40]


def current_confirmation_hold(session: Session, *, store_id: str, month: str, direction: int) -> dict | None:
    """Read the latest explicit hold event; a release remains in audit history."""
    row = session.scalar(select(FinanceOperationAudit).where(
        FinanceOperationAudit.operation_type == HOLD_OPERATION,
        FinanceOperationAudit.target_type == HOLD_TARGET,
        FinanceOperationAudit.target_id == _hold_target(store_id, month, direction),
    ).order_by(FinanceOperationAudit.id.desc()).limit(1))
    if row is None or not (row.after_snapshot or {}).get("active"):
        return None
    return {"audit_id": row.audit_id, **row.after_snapshot}


def set_confirmation_hold(session: Session, *, store_id: str, month: str, direction: int,
                          active: bool, reason: str, evidence_reference: str,
                          operator: str, request_key: str) -> FinanceOperationAudit:
    """Append an explicit hold/release event; caller owns commit and authorization.

    No scheduler or rebuild calls this writer. A release requires the same
    exact slot, operator, reason and source reference as a new explicit action.
    """
    confirmation_due_at(month)
    if direction not in (1, 2) or not all(isinstance(value, str) and value.strip()
            for value in (store_id, reason, evidence_reference, operator, request_key)):
        raise ValueError("hold requires an exact slot, reason, evidence, operator and request key")
    _lock_settlement_slot(session, store_id, month)
    payload = {"store_id": store_id, "month": month, "direction": direction,
               "active": bool(active), "reason": reason, "evidence_reference": evidence_reference}
    key = _hash([HOLD_OPERATION, request_key])
    replay = session.scalar(select(FinanceOperationAudit).where(FinanceOperationAudit.idempotency_key_hash == key))
    if replay is not None:
        if replay.request_payload_sha256 != _hash(payload):
            raise AutoConfirmationConflict("hold request key reused for a different action")
        return replay
    prior = current_confirmation_hold(session, store_id=store_id, month=month, direction=direction)
    if not active and prior is None:
        raise AutoConfirmationConflict("there is no active hold to release")
    audit = FinanceOperationAudit(audit_id="billing-hold-" + uuid4().hex,
        operation_type=HOLD_OPERATION, target_type=HOLD_TARGET,
        target_id=_hold_target(store_id, month, direction), operator_id=operator,
        operator_role=1, before_snapshot=prior, after_snapshot=payload, result_status=1,
        request_id=request_key, idempotency_key_hash=key, request_payload_sha256=_hash(payload))
    session.add(audit)
    session.flush()
    return audit


def _check_budget(session: Session) -> float:
    deadline = session.info.get(_DEADLINE_KEY)
    remaining = deadline - _wall_clock() if deadline is not None else TRANSACTION_WALL_SECONDS
    if remaining <= 0:
        raise AutoConfirmationConflict("confirmation transaction wall budget exceeded")
    return remaining


@contextmanager
def _transaction_budget(session: Session):
    """Bound reads, Python comparison, flush and commit to the same wall budget."""
    session.info[_DEADLINE_KEY] = _wall_clock() + TRANSACTION_WALL_SECONDS
    connection = session.connection()
    postgres = connection.dialect.name == "postgresql"
    sql_budget_ms = STATEMENT_TIMEOUT_MS
    if postgres:
        settings = {name: int(value) for name, value, unit in session.execute(text(
            "SELECT name, setting, unit FROM pg_settings WHERE name IN ('statement_timeout', 'lock_timeout')"))
            if unit == "ms"}
        if set(settings) != {"statement_timeout", "lock_timeout"}:
            raise AutoConfirmationConflict("database timeout evidence is unavailable")
        sql_budget_ms = min(STATEMENT_TIMEOUT_MS, settings["statement_timeout"] or STATEMENT_TIMEOUT_MS)
        lock_budget_ms = min(3000, settings["lock_timeout"] or 3000)
        session.execute(text(f"SET LOCAL statement_timeout = '{sql_budget_ms}ms'"))
        session.execute(text(f"SET LOCAL lock_timeout = '{lock_budget_ms}ms'"))

    def before_execute(_connection, cursor, _sql, _parameters, _context, _many):
        remaining = _check_budget(session)
        if postgres and remaining * 1000 < sql_budget_ms:
            # Streaming SELECTs use a named server cursor, which cannot execute
            # SET LOCAL. A separate ordinary driver cursor keeps its contract.
            with _connection.connection.dbapi_connection.cursor() as timeout_cursor:
                timeout_cursor.execute(f"SET LOCAL statement_timeout = '{max(1, int(remaining * 1000))}ms'")

    def before_commit(_session):
        remaining = _check_budget(session)
        if postgres and remaining * 1000 < sql_budget_ms:
            with connection.connection.dbapi_connection.cursor() as timeout_cursor:
                timeout_cursor.execute(f"SET LOCAL statement_timeout = '{max(1, int(remaining * 1000))}ms'")

    event.listen(connection, "before_cursor_execute", before_execute)
    event.listen(session, "before_commit", before_commit)
    try:
        _check_budget(session)
        yield
        if session.in_transaction():
            _check_budget(session)
    finally:
        event.remove(connection, "before_cursor_execute", before_execute)
        event.remove(session, "before_commit", before_commit)
        session.info.pop(_DEADLINE_KEY, None)


def _bounded_rows(session: Session, query, *, limit: int = MAX_BATCH_SOURCE_ROWS):
    """Stream a hard-capped batch; saturation refuses the whole operation."""
    cap = min(limit, MAX_BATCH_SOURCE_ROWS)
    result = session.execute(query.limit(cap + 1).execution_options(yield_per=500))
    try:
        for index, row in enumerate(result):
            _check_budget(session)
            if index >= cap:
                raise AutoConfirmationConflict("confirmation source/dependency row limit exceeded")
            yield row
    finally:
        result.close()


@contextmanager
def _postcheck_seal(session: Session):
    """Prevent business SQL or a new ORM flush after the final bounded proof."""
    connection = None

    def reject_sql(*_args):
        raise AutoConfirmationConflict("SQL after final confirmation seal")

    def reject_flush(*_args):
        raise AutoConfirmationConflict("ORM flush after final confirmation seal")

    def seal():
        nonlocal connection
        if session.new or session.dirty or session.deleted:
            raise AutoConfirmationConflict("pending ORM changes after final confirmation proof")
        connection = session.connection()
        event.listen(connection, "before_cursor_execute", reject_sql)
        event.listen(session, "before_flush", reject_flush)

    try:
        yield seal
    finally:
        if connection is not None:
            event.remove(connection, "before_cursor_execute", reject_sql)
            event.remove(session, "before_flush", reject_flush)


def _batch_dependencies(session: Session, bills: list[SettlementStatement]) -> dict:
    ids = [row.statement_id for row in bills]
    slots = sorted({(row.store_id, row.statement_month) for row in bills})
    result = {"confirmations": defaultdict(dict), "disputes": defaultdict(list),
              "holds": {}, "invoices": set(), "allocations": set()}
    if not bills:
        return result
    for (row,) in _bounded_rows(session, select(SettlementStatementConfirmation).where(
            SettlementStatementConfirmation.statement_id.in_(ids))):
        result["confirmations"][row.statement_id][row.fee_direction] = row
    for row in _bounded_rows(session, select(SettlementDispute.dispute_id, SettlementDispute.store_id,
            SettlementDispute.statement_month, SettlementDispute.fee_direction, SettlementDispute.status,
            SettlementDispute.disputed_amount_cent).where(
            tuple_(SettlementDispute.store_id, SettlementDispute.statement_month).in_(slots),
            SettlementDispute.status.in_((1, 2, 3, 4)))):
        result["disputes"][(row.store_id, row.statement_month)].append(row)
    target_ids = [_hold_target(store, month, direction) for store, month in slots for direction in (1, 2)]
    latest = select(func.max(FinanceOperationAudit.id).label("id")).where(
        FinanceOperationAudit.operation_type == HOLD_OPERATION,
        FinanceOperationAudit.target_type == HOLD_TARGET,
        FinanceOperationAudit.target_id.in_(target_ids)).group_by(FinanceOperationAudit.target_id).subquery()
    for (row,) in _bounded_rows(session, select(FinanceOperationAudit).join(latest, FinanceOperationAudit.id == latest.c.id)):
        if (row.after_snapshot or {}).get("active"):
            result["holds"][row.target_id] = {"audit_id": row.audit_id, **row.after_snapshot}
    result["invoices"] = {tuple(row) for row in _bounded_rows(session, select(
        InvoiceRecord.store_id, InvoiceRecord.statement_month, InvoiceRecord.fee_direction).where(
            tuple_(InvoiceRecord.store_id, InvoiceRecord.statement_month).in_(slots)).distinct())}
    result["allocations"] = {tuple(row) for row in _bounded_rows(session, select(
        PromotionInvoiceAllocation.store_id, PromotionInvoiceAllocation.statement_month).where(
            tuple_(PromotionInvoiceAllocation.store_id, PromotionInvoiceAllocation.statement_month).in_(slots)).distinct())}
    return result


def _month_source_proof(session: Session, month: str, generation_id: str | None) -> tuple:
    """One immutable/month proof, including publication owner and job evidence."""
    revisions = published_days_revisions(session, month)
    if revisions is None:
        return "SOURCE_INCOMPLETE", None, None
    try:
        qualification = require_current_month_qualification(session, month)
        resolution = resolve_projection_partitions(session, artifact="monthly", partition_keys=[month],
            pinned_generation_id=generation_id)[month] if generation_id else None
    except (ValueError, LineageError, AccountQualificationError):
        return "PUBLICATION_NOT_READY", None, None
    if resolution is None or resolution.source_kind not in ("overlay", "tombstone"):
        return "PUBLICATION_NOT_READY", None, None
    owner_id = resolution.actual_data_generation_id or resolution.nearest_manifest_owner_generation
    owner = session.get(SettlementProjectionGeneration, owner_id)
    source_job_ids = sorted({revision.rsplit("@", 1)[-1] for revision in revisions})
    finished = list(session.execute(select(JobRun.job_id, JobRun.finished_at).where(JobRun.job_id.in_(source_job_ids))))
    if (owner is None or owner.published_at is None or len(finished) != len(source_job_ids)
            or any(at is None for _, at in finished)):
        return "SOURCE_REVISION_EVIDENCE_MISSING", resolution, None
    if max(_utc(at) for _, at in finished) > _utc(owner.published_at):
        return "COLLECTION_NEWER_THAN_PUBLICATION", resolution, None
    token = [generation_id, owner_id, revisions,
        [qualification.version_id, qualification.content_sha256] if qualification else None]
    return None, resolution, token


def _batch_economic_proofs(session: Session, bills: list[SettlementStatement], generation_id: str | None) -> dict:
    month_proofs = {month: _month_source_proof(session, month, generation_id)
        for month in sorted({row.statement_month for row in bills})}
    output = {bill.statement_id: (month_proofs[bill.statement_month][0], None) for bill in bills}
    eligible = [bill for bill in bills if month_proofs[bill.statement_month][0] is None]
    if not eligible:
        return output
    ids = [bill.statement_id for bill in eligible]
    slots = sorted({(bill.store_id, bill.statement_month) for bill in eligible})
    entries, sources = defaultdict(list), defaultdict(list)
    for row in _bounded_rows(session, select(SettlementStatementEntry.statement_id,
            SettlementStatementEntry.source_type, SettlementStatementEntry.source_record_id,
            SettlementStatementEntry.fee_direction, SettlementStatementEntry.base_amount_cent,
            SettlementStatementEntry.fee_amount_cent).where(SettlementStatementEntry.statement_id.in_(ids))):
        entries[row[0]].append(tuple(row)[1:])
    relation = _sparse_authority_relation(tuple(sorted(month_proofs)))
    for row in _bounded_rows(session, select(relation.c.store_id, relation.c.month,
            relation.c.source_kind, relation.c.source_id, relation.c.fee_direction,
            relation.c.base_amount_cent, relation.c.fee_amount_cent).where(
            tuple_(relation.c.store_id, relation.c.month).in_(slots),
            relation.c.product_scope == "all", relation.c.product_type == "all")):
        sources[(row[0], row[1])].append((1 if row[2] == "result" else 2, *tuple(row)[3:]))
    aggregate_keys = [(month_proofs[bill.statement_month][1].actual_data_generation_id,
        bill.statement_month, bill.store_id) for bill in eligible
        if month_proofs[bill.statement_month][1].source_kind == "overlay"]
    aggregates = { (row.generation_id, row.month, row.store_id): row for (row,) in _bounded_rows(session,
        select(SettlementMonthlyOverlay).where(
            tuple_(SettlementMonthlyOverlay.generation_id, SettlementMonthlyOverlay.month,
                SettlementMonthlyOverlay.store_id).in_(aggregate_keys),
            SettlementMonthlyOverlay.product_scope == "all", SettlementMonthlyOverlay.product_type == "all",
            SettlementMonthlyOverlay.tombstone.is_(False)))} if aggregate_keys else {}
    # A missing store row is only a real zero when the formal generator recorded
    # an exactly empty source payload; arbitrary missing projections stay unknown.
    empty_audits = {row[0] for row in _bounded_rows(session, select(FinanceOperationAudit.target_id).where(
        FinanceOperationAudit.target_id.in_(ids), FinanceOperationAudit.operation_type == "GENERATE_PENDING_STATEMENT",
        FinanceOperationAudit.request_payload_sha256 == _hash([])).distinct())}
    money_fields = tuple(f"{prefix}_{kind}_fee_cent" for prefix in ("promotion", "management")
        for kind in ("original", "adjustment", "net"))
    for bill in eligible:
        _check_budget(session)
        _, resolution, token = month_proofs[bill.statement_month]
        aggregate = aggregates.get((resolution.actual_data_generation_id, bill.statement_month, bill.store_id))
        bill_entries = sorted(entries[bill.statement_id])
        authority = sorted(sources[(bill.store_id, bill.statement_month)])
        reason = None
        if any((getattr(aggregate, name) if aggregate is not None else 0) != getattr(bill, name) for name in money_fields):
            reason = "BILL_PUBLICATION_MISMATCH"
        elif bill_entries != authority:
            reason = "BILL_SOURCE_VERSION_MISMATCH"
        elif not bill_entries and bill.statement_id not in empty_audits:
            reason = "BILL_SOURCE_EVIDENCE_MISSING"
        elif aggregate is None and (bill_entries or authority):
            reason = "BILL_PUBLICATION_MISMATCH"
        output[bill.statement_id] = (reason, None if reason else _hash([*token, bill_entries]))
    return output


def _preview(session: Session, *, now: datetime, months: tuple[str, ...] = (),
             store_ids: tuple[str, ...] = (), after_id: int = 0, limit: int = 50,
             lock: bool = False) -> dict:
    if limit < 1 or limit > 200 or after_id < 0:
        raise ValueError("preview requires 1..200 statements and a nonnegative cursor")
    for month in months:
        confirmation_due_at(month)
    now = _utc(now)
    conditions = [SettlementStatement.is_current.is_(True),
        SettlementStatement.statement_month >= "2026-08", SettlementStatement.id > after_id]
    if months:
        conditions.append(SettlementStatement.statement_month.in_(months))
    if store_ids:
        conditions.append(SettlementStatement.store_id.in_(store_ids))
    active_query = select(SettlementProjectionActive).where(SettlementProjectionActive.projection_name == "settlement")
    if lock:
        active_query = active_query.with_for_update()
    active = session.scalar(active_query.execution_options(populate_existing=True))
    generation_id = active.generation_id if active else None
    bills = list(session.scalars(select(SettlementStatement).where(*conditions)
        .order_by(SettlementStatement.id).limit(limit + 1)))
    has_more = len(bills) > limit
    bills = bills[:limit]
    if lock:
        for bill in sorted(bills, key=lambda row: (row.store_id, row.statement_month)):
            _lock_settlement_slot(session, bill.store_id, bill.statement_month)
        ids = [row.statement_id for row in bills]
        bills = list(session.scalars(select(SettlementStatement).where(SettlementStatement.statement_id.in_(ids))
            .order_by(SettlementStatement.id).with_for_update().execution_options(populate_existing=True))) if ids else []
    busy = _live_heavy_job(session, now) or session.scalar(select(JobRun).where(
        JobRun.job_name == "settlement_rebuild", JobRun.status.in_(("queued", "pending", "retry_wait")))
        .order_by(JobRun.job_id).limit(1))
    dependencies = _batch_dependencies(session, bills)
    rows = []
    for bill in bills:
        _check_budget(session)
        confirmations = dependencies["confirmations"][bill.statement_id]
        slot = (bill.store_id, bill.statement_month)
        disputes = dependencies["disputes"][slot]
        frozen = {direction: sum(row.disputed_amount_cent for row in disputes
            if row.fee_direction == direction and row.status in (1, 2, 3)) for direction in (1, 2)}
        confirmable = statement_confirmable_amounts(promotion_net_fee_cent=bill.promotion_net_fee_cent,
            management_net_fee_cent=bill.management_net_fee_cent, frozen_by_direction=frozen)
        for direction, prefix in ((1, "promotion"), (2, "management")):
            existing = confirmations.get(direction)
            hold = dependencies["holds"].get(_hold_target(*slot, direction))
            reason = None
            state = "candidate"
            if existing is not None:
                state = "already_confirmed" if existing.confirmation_status == 1 else "blocked"
                reason = None if state == "already_confirmed" else "EXISTING_CONFIRMATION_PROTECTED"
            elif now < confirmation_due_at(bill.statement_month):
                state, reason = "not_due", "CONFIRMATION_WINDOW_OPEN"
            elif not bill.is_current:
                reason = "STATEMENT_VERSION_CHANGED"
            elif bill.locked_at is not None or bill.lock_version is not None or bill.statement_status == 4:
                reason = "STATEMENT_LOCKED"
            elif bill.statement_status not in (1, 2):
                reason = "STATEMENT_STATE_PROTECTED"
            elif hold:
                reason = "EXPLICIT_REVIEW_HOLD"
            elif any(row.fee_direction == direction for row in disputes):
                reason = "DISPUTE_PROTECTED"
            elif (*slot, direction) in dependencies["invoices"] or (direction == 1 and slot in dependencies["allocations"]):
                reason = "INVOICE_FACT_PROTECTED"
            elif busy is not None:
                reason = "SOURCE_JOB_ACTIVE"
            if reason and state == "candidate":
                state = "blocked"
            rows.append({"statement_id": bill.statement_id, "store_id": bill.store_id,
                "month": bill.statement_month, "version": bill.version_no, "direction": direction,
                "amount_cent": confirmable["PROMOTION" if direction == 1 else "MANAGEMENT"],
                "statement_amount_cent": getattr(bill, f"{prefix}_net_fee_cent"), "state": state, "reason": reason,
                "due_at": confirmation_due_at(bill.statement_month).isoformat(),
                "confirmation_id": existing.confirmation_id if existing else None,
                "confirmed_at": existing.confirmed_at.isoformat() if existing else None,
                "confirmed_by": existing.confirmed_by if existing else None,
                "hold": hold, "source_proof": None,
                "bill_state": [bill.statement_status, bill.confirmed_by, bill.confirmed_at, bill.locked_at, bill.lock_version],
                "disputes": sorted((row.dispute_id, row.fee_direction, row.status) for row in disputes),
            })
    candidate_ids = {row["statement_id"] for row in rows if row["state"] == "candidate"}
    proofs = _batch_economic_proofs(session, [bill for bill in bills if bill.statement_id in candidate_ids], generation_id)
    for row in rows:
        if row["state"] == "candidate":
            reason, proof = proofs[row["statement_id"]]
            row["source_proof"] = proof
            if reason:
                row["state"], row["reason"] = "blocked", reason
    result = {"protocol": PROTOCOL, "scheduler_enabled": auto_confirmation_enabled(),
        "months": list(months), "store_ids": list(store_ids),
        "after_id": after_id, "limit": limit, "has_more": has_more,
        "next_after_id": bills[-1].id if bills else after_id, "generation_id": generation_id,
        "rows": rows, "counts": dict(Counter(row["state"] for row in rows))}
    result["preview_hash"] = _hash(result)
    return result


def preview_auto_confirmation(factory: sessionmaker, *, now: datetime | None = None,
                              months: tuple[str, ...] = (), store_ids: tuple[str, ...] = (),
                              after_id: int = 0, limit: int = 50) -> dict:
    """Return a read-only exact batch, including explicit reasons for each refusal."""
    with factory() as session, _transaction_budget(session):
        return _preview(session, now=now or datetime.now(timezone.utc), months=months,
            store_ids=store_ids, after_id=after_id, limit=limit)


def apply_auto_confirmation(factory: sessionmaker, *, preview_hash: str,
                            months: tuple[str, ...] = (), store_ids: tuple[str, ...] = (),
                            after_id: int = 0, limit: int = 50, now: datetime | None = None) -> dict:
    """Confirm only still-eligible directions of the exact reviewed batch, atomically."""
    if not isinstance(preview_hash, str) or len(preview_hash) != 64 or any(ch not in "0123456789abcdef" for ch in preview_hash):
        raise ValueError("apply requires an exact lowercase SHA-256 preview hash")
    now = _utc(now or datetime.now(timezone.utc))
    scope = {"months": list(months), "store_ids": list(store_ids), "after_id": after_id, "limit": limit}
    batch_key = _hash(["billing-auto-confirm-batch", preview_hash])
    with factory.begin() as session, _transaction_budget(session), _postcheck_seal(session) as seal:
        if session.get_bind().dialect.name == "postgresql":
            if not session.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY))):
                raise AutoConfirmationConflict("source claim lock is busy")
        replay = session.scalar(select(FinanceOperationAudit).where(
            FinanceOperationAudit.idempotency_key_hash == batch_key))
        if replay is not None:
            if replay.request_payload_sha256 != _hash(scope):
                raise AutoConfirmationConflict("batch hash was used with a different scope")
            result = {"protocol": PROTOCOL, "preview_hash": preview_hash, "replayed": True,
                "confirmed_count": 0, "original_confirmed_count": (replay.after_snapshot or {}).get("confirmed_count", 0),
                "confirmation_ids": list((replay.after_snapshot or {}).get("confirmation_ids", [])), "confirmed": [], "blocked": []}
            # A replay is a read, including transaction completion. Do not let
            # the outer begin context implicitly commit after its budget/seal
            # guards have exited. Copy the receipt before rollback expires it.
            session.rollback()
            return result
        preview = _preview(session, now=now, months=months, store_ids=store_ids,
            after_id=after_id, limit=limit, lock=True)
        if preview["preview_hash"] != preview_hash:
            raise AutoConfirmationConflict("preview changed; review a fresh dry-run")
        written = []
        for row in preview["rows"]:
            if row["state"] != "candidate":
                continue
            identity = [row["statement_id"], row["version"], row["direction"]]
            key = _hash([PROTOCOL, *identity])
            confirmation = SettlementStatementConfirmation(confirmation_id="auto-confirmation-" + key[:40],
                statement_id=row["statement_id"], fee_direction=row["direction"], confirmation_status=1,
                confirmed_amount_cent=row["amount_cent"], confirmed_by="system:auto-confirmation",
                confirmed_at=now, idempotency_key_hash=key, request_payload_sha256=_hash(row))
            session.add(confirmation)
            audit = FinanceOperationAudit(audit_id="auto-confirmation-audit-" + key[:40],
                operation_type="AUTO_CONFIRM_STATEMENT", target_type="STATEMENT_CONFIRMATION",
                target_id=confirmation.confirmation_id, operator_id="system:auto-confirmation", operator_role=1,
                before_snapshot={"statementId": row["statement_id"], "version": row["version"], "direction": row["direction"]},
                after_snapshot={"confirmationId": confirmation.confirmation_id, "amountCent": row["amount_cent"],
                    "sourceProof": row["source_proof"], "previewHash": preview_hash},
                result_status=1, request_id="auto-confirm-" + preview_hash[:40], request_payload_sha256=_hash(row))
            session.add(audit)
            written.append({**row, "confirmation_id": confirmation.confirmation_id,
                "audit_id": audit.audit_id, "confirmed_at": now.isoformat()})
        session.add(FinanceOperationAudit(audit_id="auto-confirm-batch-" + preview_hash[:40],
            operation_type="AUTO_CONFIRM_BATCH", target_type="AUTO_CONFIRM_BATCH", target_id=preview_hash,
            operator_id="system:auto-confirmation", operator_role=1,
            before_snapshot=scope, after_snapshot={"confirmed_count": len(written),
                "confirmation_ids": [row["confirmation_id"] for row in written]}, result_status=1,
            request_id="auto-confirm-" + preview_hash[:40], idempotency_key_hash=batch_key,
            request_payload_sha256=_hash(scope)))
        session.flush()
        if session.get_bind().dialect.name == "postgresql":
            # PostgreSQL's statement_timeout does not bound work deferred until
            # COMMIT. Force deferred constraints/triggers into an ordinary SQL
            # statement, where the remaining wall-budget timeout is effective.
            session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        _check_budget(session)
        seal()
        result = {"protocol": PROTOCOL, "preview_hash": preview_hash, "replayed": False, "confirmed_count": len(written),
                "confirmed": written, "blocked": [row for row in preview["rows"] if row["state"] == "blocked"]}
        session.commit()
        return result


def process_due_auto_confirmations(factory: sessionmaker) -> bool:
    """Opt-in hourly scan, one bounded batch per tick; late bills remain retryable."""
    if not auto_confirmation_enabled():
        return False
    now = datetime.now(timezone.utc)
    hour = now.strftime("%Y%m%d%H")
    with factory() as session:
        attempt = session.scalar(select(JobRun).where(JobRun.job_name == "billing_auto_confirmation")
            .order_by(JobRun.started_at.desc(), JobRun.job_id.desc()).limit(1))
        if attempt and attempt.status == "failed" and attempt.started_at and _utc(attempt.started_at) > now - timedelta(minutes=5):
            return False
        last = session.scalar(select(JobRun).where(JobRun.job_name == "billing_auto_confirmation",
            JobRun.status == "success", JobRun.job_id.like(f"billing-auto-confirm-{hour}-%"))
            .order_by(JobRun.finished_at.desc()).limit(1))
        if last and not (last.metadata_json or {}).get("has_more"):
            return False
        cursor = int((last.metadata_json or {}).get("next_after_id", 0)) if last else 0
    try:
        preview = preview_auto_confirmation(factory, now=now, after_id=cursor)
        result = apply_auto_confirmation(factory, now=now, preview_hash=preview["preview_hash"], after_id=cursor)
        with factory.begin() as session:
            session.add(JobRun(job_id=f"billing-auto-confirm-{hour}-{uuid4().hex[:12]}",
                job_name="billing_auto_confirmation", status="success", started_at=now, finished_at=datetime.now(timezone.utc),
                metadata_json={"protocol": PROTOCOL, "enabled": True, "counts": preview["counts"],
                    "blocked_reasons": dict(Counter(row["reason"] for row in preview["rows"] if row["state"] == "blocked")),
                    "confirmed_count": result["confirmed_count"], "preview_hash": preview["preview_hash"],
                    "next_after_id": preview["next_after_id"], "has_more": preview["has_more"]}))
    except Exception as exc:
        LOGGER.exception("billing auto-confirmation scan failed; no reviewed result is assumed complete")
        with factory.begin() as session:
            session.add(JobRun(job_id=f"billing-auto-confirm-{hour}-{uuid4().hex[:12]}",
                job_name="billing_auto_confirmation", status="failed", started_at=now, finished_at=datetime.now(timezone.utc),
                metadata_json={"protocol": PROTOCOL, "enabled": True, "after_id": cursor,
                    "error_type": type(exc).__name__}))
        return True
    return True
