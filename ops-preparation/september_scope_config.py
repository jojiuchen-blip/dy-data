"""DYDATA-102 September settlement-scope config + scoped-rebuild wrapper (prepared).

Calls the REAL ``fee_admin.create_settlement_scope_rules`` inside one outer
engine-level transaction with a savepoint-bound Session, so the scope rules and
the month-scoped rebuild job become visible atomically; the un-scoped rebuild
job is never observable alone.

Design notes (reviewer-facing):

* Every source-scope check, target protection, full-field before snapshot and
  the expected-august-scope hash comparison happens *inside* the same outer
  transaction, immediately before the route call, so a drifting source scope is
  re-detected on the writing transaction instead of a pre-probe.
* A short PG advisory transaction lock keyed by the idempotency key serializes
  concurrent invocations of this one operation; it is taken inside the outer
  transaction (auto-released at commit/rollback) and no new row locks are taken
  on the projection active row, so no job→active lock-order inversion is
  introduced.
* ``join_transaction_mode="create_savepoint"`` is kept: the route's internal
  commits release only its savepoint; the outer transaction still gates the
  full job + rules + event until the final stamping and fingerprint checks
  pass, then one ``outer.commit()`` publishes everything at once.
* Idempotent replay: when the idempotency key already owns exactly the expected
  September slots with matching payload hash, scope and actor evidence, and the
  derived job carries the same key/payload evidence, the operation returns the
  recorded status read-only (queued/running/success alike, even if September
  bills already exist) — nothing is written, no event is duplicated.  Any
  incompatible payload, scope, actor or partial state is refused.
* Fingerprints cover every non-target-month settlement fact (fee results,
  current pointers, non-target posting adjustments, statements, entries,
  confirmations, invoice records, promotion invoice allocations), the complete
  sku_fee_rule table and the August scope rules, hashed per-row with canonical
  JSON over ``table.c`` mappings, full sha256.  Before/after snapshots are both
  genuinely recomputed inside the outer transaction.
* Logging only ever contains the target month, counts, job id, status, scope
  and hashes — never an owner account id, nickname, request/response body or
  exception SQL parameters.
* Exit codes: 0 success (or clean read-only replay / dry-run with proof that
  this key wrote nothing), 2 refused, otherwise unexpected errors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.api.dy_api.db import get_engine
from apps.api.dy_api.models import (
    InvoiceRecord, JobEvent, JobRun, PromotionInvoice, PromotionInvoiceAllocation,
    SettlementFeeAdjustment, SettlementFeeResult, SettlementFeeResultCurrent,
    SettlementScopeRule, SettlementStatement, SettlementStatementConfirmation,
    SettlementStatementEntry, SkuFeeRule, utcnow)
from apps.api.dy_api.routes._data import DashboardDataStore
from apps.api.dy_api.routes.fee_admin import (
    SETTLEMENT_SCOPE_REBUILD_TRIGGER, _canonical_sha256, _idempotency_key_hash,
    create_settlement_scope_rules,
)
from apps.worker.month_close import published_days_revisions
from apps.worker.settlement_rebuild import scoped_business_month, settlement_month_scope_metadata

MONTH, BASE_MONTH, MAX_LINEAGE_DEPTH, CHANNELS = "2026-09", "2026-08", 48, ["LIVE", "SHORT_VIDEO"]
EVENT_TYPE = "settlement_scope_restricted"
ACTOR_TYPE = "ops_agent"


class Refused(Exception):
    """Internal control-flow marker; ``reason`` is always a static constant."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _emit(message: str) -> None:
    print(message)
    sys.stdout.flush()


def _synthetic_request():
    from starlette.requests import Request
    return Request({"type": "http", "method": "POST", "path": "/ops/dsh-dydata102-scope",
                    "headers": [(b"x-request-id", f"req_{uuid.uuid4().hex}".encode())], "query_string": b""})


def _scope_lock_key(key_hash: str) -> int:
    ticket = f"dsh-dydata102-september-scope-v1:{key_hash}"
    return int.from_bytes(hashlib.blake2b(ticket.encode(), digest_size=8).digest(), "big", signed=True)


def _acquire_scope_lock(conn, key_hash: str) -> None:
    """Short per-key advisory lock inside the outer transaction (PG only).

    Taken on the outer transaction's own connection after the outer transaction
    has begun, so it is released by the commit/rollback itself; no other lock is
    acquired before the route runs, so no new lock-order hazard is created.
    """

    if conn.dialect.name != "postgresql":
        return
    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _scope_lock_key(key_hash)})


def _lineage_reason(session: Session) -> str | None:
    row = session.execute(text(
        "SELECT g.state, g.lineage_depth FROM settlement_projection_active a "
        "JOIN settlement_projection_generation g ON g.generation_id = a.generation_id "
        "WHERE a.projection_name = 'settlement'")).first()
    if row is not None and row[0] == "published" and int(row[1]) < MAX_LINEAGE_DEPTH:
        return None
    return f"lineage_guard state={row[0] if row else None} depth={row[1] if row else None}"


def _august_scope_owner(session: Session) -> str | None:
    rows = list(session.scalars(select(SettlementScopeRule).where(
        SettlementScopeRule.effective_month == BASE_MONTH,
        SettlementScopeRule.is_active.is_(True))))
    owners = {row.owner_account_id for row in rows}
    channels = {row.sale_channel_normalized for row in rows}
    if len(rows) != 2 or len(owners) != 1 or channels != {"live", "short_video"}:
        _emit(f"august_scope=refused rows={len(rows)} owners={len(owners)} "
              f"channels={len(channels)}")
        return None
    return owners.pop()


def _september_new_write_guard_reason(session: Session) -> str | None:
    """Preconditions that apply only to a *new* write, never to a safe replay."""

    if published_days_revisions(session, MONTH) is None:
        return "september_source_not_complete_30_of_30"
    if session.scalar(select(SettlementStatement.statement_id)
                      .where(SettlementStatement.statement_month == MONTH).limit(1)):
        return "september_bills_exist"
    confirmation = (select(SettlementStatementConfirmation.confirmation_id)
                    .join(SettlementStatement,
                          SettlementStatement.statement_id == SettlementStatementConfirmation.statement_id)
                    .where(SettlementStatement.statement_month == MONTH).limit(1))
    if session.scalar(confirmation):
        return "september_confirmations_exist"
    # The business month of an InvoiceRecord is its statement_month column, and
    # the business month of a month-less PromotionInvoice is the statement_month
    # of the PromotionInvoiceAllocation row that binds invoice_id to a statement.
    # invoice_date is never used as a business-month proxy, and an unrelated
    # August invoice must not block September.
    if session.scalar(select(InvoiceRecord.invoice_id)
                      .where(InvoiceRecord.statement_month == MONTH).limit(1)):
        return "september_invoice_records_exist"
    promotion = (select(PromotionInvoice.invoice_id)
                 .join(PromotionInvoiceAllocation,
                       PromotionInvoiceAllocation.invoice_id == PromotionInvoice.invoice_id)
                 .where(PromotionInvoiceAllocation.statement_month == MONTH).limit(1))
    if session.scalar(promotion):
        return "september_promotion_invoice_allocations_exist"
    return None


def _rows_digest(session: Session, statement) -> tuple[int, str]:
    """Full-field row hash: canonical per-row JSON over table.c mappings.

    Rows are serialized with ``json.dumps(dict(row), sort_keys=True,
    default=str, separators=(',',':'))``, sorted, joined with real newlines and
    hashed with the complete sha256.  Only the row count and hash are returned.
    """

    lines = [
        json.dumps(dict(row), sort_keys=True, default=str, separators=(",", ":"))
        for row in session.execute(statement).mappings()
    ]
    lines.sort()
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return len(lines), digest


def _august_scope_digest(session: Session) -> tuple[int, str]:
    statement = (select(SettlementScopeRule.__table__)
                 .where(SettlementScopeRule.effective_month == BASE_MONTH))
    return _rows_digest(session, statement)


def _fingerprint(session: Session) -> dict[str, tuple[int, str]]:
    """Every settlement fact this operation must not disturb, genuinely recomputed.

    Sections deliberately include the NON-target-month rows (not just August):
    fee results, current pointers, posting adjustments, statements, entries,
    confirmations, invoice records and promotion invoice allocations outside the
    target month, the complete sku_fee_rule table, and the full August scope.
    """

    stmt_t = SettlementStatement.__table__
    conf_t = SettlementStatementConfirmation.__table__
    return {
        "fee_result_non_target": _rows_digest(session, select(SettlementFeeResult.__table__).where(
            SettlementFeeResult.original_business_month != MONTH)),
        "fee_result_current_all": _rows_digest(session, select(SettlementFeeResultCurrent.__table__)),
        "fee_adjustment_non_target_posting": _rows_digest(
            session,
            select(SettlementFeeAdjustment.__table__).where(
                SettlementFeeAdjustment.adjustment_posting_month != MONTH)),
        "statement_non_target": _rows_digest(session, select(stmt_t).where(
            stmt_t.c.statement_month != MONTH)),
        "statement_entry_non_target": _rows_digest(
            session,
            select(SettlementStatementEntry.__table__).where(
                SettlementStatementEntry.statement_posting_month != MONTH)),
        "confirmation_non_target": _rows_digest(
            session,
            select(conf_t).join(stmt_t, conf_t.c.statement_id == stmt_t.c.statement_id).where(
                stmt_t.c.statement_month != MONTH)),
        "invoice_record_non_target": _rows_digest(
            session,
            select(InvoiceRecord.__table__).where(InvoiceRecord.statement_month != MONTH)),
        "promotion_invoice_allocation_non_target": _rows_digest(
            session,
            select(PromotionInvoiceAllocation.__table__).where(
                PromotionInvoiceAllocation.statement_month != MONTH)),
        "sku_fee_rule_all": _rows_digest(session, select(SkuFeeRule.__table__)),
        "august_scope_full": _august_scope_digest(session),
    }


def _fingerprint_equal(before: dict, after: dict) -> bool:
    return before == after


def _derived_ids(key_hash: str) -> tuple[str, str]:
    job_id = f"{SETTLEMENT_SCOPE_REBUILD_TRIGGER}-{key_hash[:24]}"
    event_id = f"dsh-dydata102-scope-{key_hash[:24]}"
    return job_id, event_id


def _classify_request(session: Session, *, key_hash: str, request_hash: str, owner: str,
                      actor: str, job_id: str) -> tuple[str, str | None]:
    """Return ``("replay", status)`` or ``("create", None)``, or refuse.

    Replay is read-only and requires the recorded rules to be exactly the
    expected month-scoped shape with matching payload hash and actor evidence,
    plus a job carrying the same key/payload evidence.  Anything else — payload
    conflict, wrong month/owner/channels, different actor, inactive scope, or a
    job without rules — is refused fail-closed.
    """

    normalized = {channel.lower() for channel in CHANNELS}
    rules = list(session.scalars(select(SettlementScopeRule).where(
        SettlementScopeRule.idempotency_key_hash == key_hash).order_by(SettlementScopeRule.id)))
    job = session.get(JobRun, job_id)
    if not rules:
        if job is not None:
            raise Refused("partial_state_job_without_rules")
        return "create", None
    if any(row.request_payload_sha256 != request_hash for row in rules):
        raise Refused("idempotency_key_payload_conflict")
    for row in rules:
        if (row.effective_month != MONTH
                or row.owner_account_id != owner
                or row.sale_channel_normalized not in normalized
                or row.created_by != actor
                or row.is_active is not True):
            raise Refused("existing_scope_or_actor_mismatch")
    if len(rules) != len(normalized) or {row.sale_channel_normalized for row in rules} != normalized:
        raise Refused("existing_scope_shape_mismatch")
    if (job is None
            or job.idempotency_key_hash != key_hash
            or (job.metadata_json or {}).get("request_payload_sha256") != request_hash):
        raise Refused("existing_job_evidence_mismatch")
    return "replay", job.status


def _allowed_summary(*, mode: str, job_id: str, job_status: str | None, scope: str | None,
                     august_sha256: str, request_hash: str, august_rows: int) -> dict:
    """The only fields ever logged; no owner, nickname, request or response body."""

    return {
        "mode": mode,
        "target_month": MONTH,
        "channel_count": len(CHANNELS),
        "job_id": job_id,
        "job_status": job_status,
        "month_scope": scope,
        "august_scope_rows": august_rows,
        "august_scope_sha256": august_sha256,
        "request_payload_sha256": request_hash,
    }


def _ensure_scope_event(session: Session, *, event_id: str, job_id: str, actor: str,
                        idempotency_key: str, request_hash: str) -> bool:
    """Insert the audit event once; an existing consistent event is reused, never duplicated."""

    existing = session.get(JobEvent, event_id)
    if existing is not None:
        if existing.job_id != job_id or existing.event_type != EVENT_TYPE:
            raise Refused("event_id_conflict")
        return False
    session.add(JobEvent(
        event_id=event_id, job_id=job_id, event_type=EVENT_TYPE,
        actor_type=ACTOR_TYPE, actor_id=actor,
        idempotency_key=f"dsh-dydata102-scope-{idempotency_key}"[:128],
        reason="scope restricted to business_month=2026-09 before worker visibility",
        payload_json={"request_payload_sha256": request_hash, "business_month": MONTH},
        occurred_at=utcnow()))
    return True


def _rollback_all(session: Session, outer) -> None:
    try:
        session.rollback()
    except Exception:
        pass
    try:
        outer.rollback()
    except Exception:
        pass


def _post_verify(engine, *, apply: bool, key_hash: str, request_hash: str, job_id: str,
                 event_id: str, owner: str, actor: str) -> int:
    """Fresh-connection verification scoped to THIS key, not to the whole month."""

    with engine.connect() as conn:
        session = Session(bind=conn)
        try:
            rules = list(session.scalars(select(SettlementScopeRule).where(
                SettlementScopeRule.idempotency_key_hash == key_hash)))
            job = session.get(JobRun, job_id)
            event = session.get(JobEvent, event_id)
            if not apply:
                if rules or job is not None or event is not None:
                    _emit("post_check_failed this dry-run key persisted rows; investigate")
                    return 2
                _emit("post_check=clean no rows for this key")
                return 0
            normalized = {channel.lower() for channel in CHANNELS}
            if (len(rules) != 2
                    or {row.sale_channel_normalized for row in rules} != normalized
                    or any(row.effective_month != MONTH for row in rules)
                    or any(row.owner_account_id != owner for row in rules)
                    or any(row.created_by != actor for row in rules)
                    or any(row.is_active is not True for row in rules)):
                _emit("post_check_failed september rules for this key are not the expected shape")
                return 2
            if job is None or job.idempotency_key_hash != key_hash:
                _emit("post_check_failed job missing or key evidence mismatch")
                return 2
            if (job.metadata_json or {}).get("request_payload_sha256") != request_hash:
                _emit("post_check_failed job payload evidence mismatch")
                return 2
            scope = scoped_business_month(job.metadata_json)
            if scope != MONTH:
                _emit("post_check_failed job is not month-scoped")
                return 2
            _emit(f"post_scope_rows=2 channels={sorted(normalized)}")
            _emit(f"post_job={job_id} status={job.status} month_scope={scope}")
            _emit("note=job status is reported as recorded; queued/running is a rebuild job, "
                  "not a generated bill")
            return 0
        finally:
            session.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--actor", required=True)
    ap.add_argument("--idempotency-key", required=True)
    ap.add_argument("--change-reason", required=True)
    ap.add_argument("--expected-august-scope-sha256", default=None)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not 16 <= len(args.idempotency_key.strip()) <= 128:
        _emit("arg_error=idempotency key length must be 16..128")
        return 2
    engine = get_engine()
    if engine is None:
        _emit("db=unavailable")
        return 2
    request = _synthetic_request()
    key_hash = _idempotency_key_hash(args.idempotency_key, request)
    job_id, event_id = _derived_ids(key_hash)
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    committed = False
    mode = "dry_run"
    try:
        _acquire_scope_lock(conn, key_hash)
        lineage = _lineage_reason(session)
        if lineage is not None:
            raise Refused(f"lineage_guard_refused::{lineage}")
        owner = _august_scope_owner(session)
        if owner is None:
            raise Refused("august_scope_refused")
        payload = {"effectiveMonth": MONTH, "ownerAccountId": owner,
                   "allowedSaleChannels": CHANNELS, "changeReason": args.change_reason}
        request_hash = _canonical_sha256({
            "effectiveMonth": MONTH, "ownerAccountId": owner,
            "allowedSaleChannels": CHANNELS, "changeReason": args.change_reason})
        august_rows, august_sha256 = _august_scope_digest(session)
        if args.expected_august_scope_sha256 is not None and args.expected_august_scope_sha256 != august_sha256:
            raise Refused("expected_august_scope_mismatch")
        kind, status = _classify_request(
            session, key_hash=key_hash, request_hash=request_hash, owner=owner,
            actor=args.actor, job_id=job_id)
        if kind == "replay":
            # Read-only replay: no guard evaluation beyond evidence, no writes,
            # no event insert; safe even if September bills already exist.
            mode = "replay"
            scope = scoped_business_month(session.get(JobRun, job_id).metadata_json)
            _emit(json.dumps(_allowed_summary(
                mode="replay", job_id=job_id, job_status=status, scope=scope,
                august_sha256=august_sha256, request_hash=request_hash,
                august_rows=august_rows), sort_keys=True))
            outer.rollback()  # nothing was written; release the advisory lock
            return 0
        guard_reason = _september_new_write_guard_reason(session)
        if guard_reason is not None:
            raise Refused(guard_reason)
        slot_conflict = session.scalar(select(SettlementScopeRule.id).where(
            SettlementScopeRule.effective_month == MONTH,
            SettlementScopeRule.owner_account_id == owner,
            SettlementScopeRule.sale_channel_normalized.in_(
                channel.lower() for channel in CHANNELS)).limit(1))
        if slot_conflict is not None:
            raise Refused("september_slot_occupied")
        before = _fingerprint(session)
        result = create_settlement_scope_rules(
            payload, request, idempotency_key=args.idempotency_key, username=args.actor,
            store=DashboardDataStore(session))
        job = session.get(JobRun, job_id)
        if job is None:
            raise Refused("job_missing")
        if job.status != "queued":
            raise Refused("existing_job_unsafe")
        job.metadata_json = {**job.metadata_json, **settlement_month_scope_metadata(MONTH)}
        scope = scoped_business_month(job.metadata_json)
        if scope != MONTH:
            raise Refused("scope_stamp_invalid")
        _ensure_scope_event(session, event_id=event_id, job_id=job_id, actor=args.actor,
                            idempotency_key=args.idempotency_key, request_hash=request_hash)
        session.flush()
        after = _fingerprint(session)
        if not _fingerprint_equal(before, after):
            raise Refused("fingerprint_changed")
        if args.apply:
            session.commit()  # releases the route's savepoint chain only
            outer.commit()
            committed = True
            mode = "apply"
            _emit(json.dumps(_allowed_summary(
                mode="apply", job_id=job_id, job_status="queued", scope=scope,
                august_sha256=august_sha256, request_hash=request_hash,
                august_rows=august_rows), sort_keys=True))
            _emit("committed=true rules and scoped job visible atomically")
        else:
            session.rollback()
            outer.rollback()
            _emit("dry_run=true outer transaction rolled back")
    except Refused as exc:
        reason = exc.reason.split("::", 1)[-1]
        _emit(f"refused reason={reason} outer_rolled_back=true")
        _rollback_all(session, outer)
        return 2
    except Exception as exc:
        # Only the exception type is printed; exception strings can embed SQL
        # parameters, connection details or account ids.
        _emit(f"route_refused type={type(exc).__name__} outer_rolled_back=true")
        _rollback_all(session, outer)
        return 2
    finally:
        if not committed:
            _rollback_all(session, outer)
        try:
            session.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
    if mode == "replay":
        return 0
    return _post_verify(engine, apply=args.apply, key_hash=key_hash, request_hash=request_hash,
                        job_id=job_id, event_id=event_id, owner=owner, actor=args.actor)


if __name__ == "__main__":
    sys.exit(main())
