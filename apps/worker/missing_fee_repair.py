"""Exact, synchronous first-fee repair; private reviewed manifests are mandatory.

Preview performs SELECTs only. Apply owns a fresh PostgreSQL transaction, fences
all calculation dependencies, re-quotes, and fails closed on any disagreement.
There is deliberately no month rebuild, queue, recovery or batch fallback.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import re
import time
from typing import Any

from sqlalchemy import event, func, or_, select, text, tuple_
from sqlalchemy.orm import Session

from apps.api.dy_api import models as m
from apps.worker.repositories import HEAVY_SYNC_CLAIM_LOCK_KEY

OPERATION = "EXACT_FIRST_MISSING_FEE_REPAIR"
BUDGET = {"max_coupons": 500, "lock_timeout_ms": 1000,
          "statement_timeout_ms": 5000, "transaction_wall_seconds": 30}
EXCLUSION_GROUPS = frozenset({"paused22", "cohort106", "fuyang", "protected"})


class MissingFeeRepairError(ValueError):
    """The whole reviewed batch is ineligible or changed."""


class NewFeeQuoteError(MissingFeeRepairError):
    """The normal calculator cannot produce a first fee without writing."""


class MissingFeeBudgetError(MissingFeeRepairError):
    """The short synchronous transaction exhausted its fixed budget."""


@dataclass(frozen=True)
class NewFeeQuote:
    """Complete business snapshot of a first immutable fee result."""

    coupon_id: str
    order_id: str
    fee_direction: int
    original_business_month: str
    rule_match_date: date
    sale_store_id: str
    verify_store_id: str | None
    sku_id: str
    product_scope: str
    product_type: str
    sale_channel_normalized: str
    source_amount_cent: int
    refunded_amount_cent: int
    fee_base_cent: int
    fee_rate: Decimal
    fee_amount_cent: int
    rule_version: str
    scope_rule_version: str
    result_status: int
    input_fingerprint: str
    qualifying_verify_id: str
    qualifying_verify_time: datetime
    qualifying_verify_store_id: str
    qualifying_verify_store_name: str
    sale_attribution_decision_id: str | None
    account_qualification_version_id: str | None
    reverification_anchor_id: str | None = None


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported canonical type: {type(value).__name__}")


def canonical(value: Any) -> Any:
    """Return a JSON-safe canonical copy, preserving every supplied field."""
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":"), default=_plain, allow_nan=False))


def digest(value: Any) -> str:
    """Hash canonical private input or calculation evidence."""
    return sha256(json.dumps(canonical(value), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def _required_text(value: Any, field: str, limit: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > limit:
        raise MissingFeeRepairError(f"invalid {field}")
    return value


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise MissingFeeRepairError("verify_time must be an ISO timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MissingFeeRepairError("invalid verify_time") from exc
    if parsed.tzinfo is None:
        raise MissingFeeRepairError("verify_time must include timezone")
    return parsed


def validate_request(manifest: dict, exclusions: dict) -> dict:
    """Validate exact identities and all four explicit exclusion groups."""
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise MissingFeeRepairError("manifest schema_version must be 1")
    for field in ("request_id", "approval_ref", "actor"):
        _required_text(manifest.get(field), field)
    if not re.fullmatch(r"ops:[A-Za-z0-9][A-Za-z0-9:._-]*", manifest["actor"]):
        raise MissingFeeRepairError("actor must be an explicit ops identity")
    coupons = manifest.get("coupons")
    if not isinstance(coupons, list) or not 1 <= len(coupons) <= BUDGET["max_coupons"]:
        raise MissingFeeRepairError("manifest requires 1..500 exact coupons; no automatic batching")
    identities = set()
    raw_ids = set()
    for entry in coupons:
        if not isinstance(entry, dict):
            raise MissingFeeRepairError("invalid coupon identity")
        for field in ("coupon_id", "order_id", "business_month", "expected_sale_store_id",
                      "expected_verify_store_id", "verify_id"):
            _required_text(entry.get(field), field)
        for field in ("raw_order_id", "raw_coupon_id"):
            value = entry.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise MissingFeeRepairError(f"invalid {field}")
        if entry["coupon_id"] in identities or entry["raw_coupon_id"] in raw_ids:
            raise MissingFeeRepairError("duplicate coupon identity")
        identities.add(entry["coupon_id"])
        raw_ids.add(entry["raw_coupon_id"])
        if entry["business_month"] not in {"2026-08", "2026-09"}:
            raise MissingFeeRepairError("repair supports August/September 2026 only")
        from apps.worker.settlement import SHANGHAI
        if _instant(entry.get("verify_time")).astimezone(SHANGHAI).strftime("%Y-%m") != entry["business_month"]:
            raise MissingFeeRepairError("verify timestamp is outside exact approved month")
    if (not isinstance(exclusions, dict) or exclusions.get("schema_version") != 1
            or not isinstance(exclusions.get("groups"), dict)
            or set(exclusions["groups"]) != EXCLUSION_GROUPS):
        raise MissingFeeRepairError("four named exclusion groups are required")
    for name, group in exclusions["groups"].items():
        values = group.get("coupon_ids") if isinstance(group, dict) else None
        if (not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values)
                or len(set(values)) != len(values) or type(group.get("count")) is not int
                or group["count"] != len(values) or group.get("sha256") != digest(sorted(values))):
            raise MissingFeeRepairError(f"invalid exclusion group count/hash: {name}")
        if identities.intersection(values):
            raise MissingFeeRepairError(f"manifest intersects excluded group: {name}")
    # Bind the complete supplied documents, not a projection of known fields.
    return {"operation": OPERATION, "manifest": canonical(manifest),
            "exclusions": canonical(exclusions), "budget": dict(BUDGET)}


def _rows(session: Session, table, condition=None) -> list[dict]:
    query = select(table).order_by(*table.primary_key.columns)
    if condition is not None:
        query = query.where(condition)
    return [canonical(dict(row)) for row in session.execute(query).mappings()]


def _table(name: str):
    return m.Base.metadata.tables[name]


# All non-raw lookup relations reachable from the normal calculator. Full small
# configuration snapshots also detect insertion of a previously absent match.
CONFIG_MODELS = (m.DimSkuProductRule, m.SkuFeeRule, m.SettlementScopeRule,
                 m.RawAwemeBinding, m.DimAwemeAccount, m.DimNonCommissionOwnerAccount,
                 m.DimStorePoiMapping, m.DimStore)
HISTORY_MODELS = (m.SettlementFeeResult, m.SettlementFeeResultCurrent,
                  m.SettlementFeeAdjustment, m.SettlementCarryforwardSource,
                  m.SettlementStatementEntry)
SLOT_MODELS = (m.SettlementStatement, m.SettlementStatementConfirmation,
               m.SettlementDispute, m.InvoiceRecord, m.PromotionInvoiceAllocation)


def _budget(started: float) -> None:
    if time.monotonic() - started >= BUDGET["transaction_wall_seconds"]:
        raise MissingFeeBudgetError("30 second whole-transaction budget exhausted; batch rolled back")


def quote_new_fee(session: Session, *, coupon: m.RawDouyinOrderCoupon,
                  order: m.RawDouyinOrder, direction: int) -> NewFeeQuote:
    """Invoke the shared calculator with autoflush disabled and no side effects."""
    from apps.worker.settlement import _materialize_dual_fee_direction
    if session.new or session.dirty or session.deleted:
        raise NewFeeQuoteError("quote requires a clean session")
    with session.no_autoflush:
        quote = _materialize_dual_fee_direction(
            session, order=order, coupon=coupon, direction=direction,
            calculation_run_id="quote-only", current=None, quote_only=True,
        )
    if not isinstance(quote, NewFeeQuote):
        raise NewFeeQuoteError("calculator did not return a complete quote")
    if session.new or session.dirty or session.deleted:
        raise NewFeeQuoteError("quote unexpectedly dirtied session")
    return quote


def _source_dependencies(session: Session, entries: list[dict]) -> dict:
    coupon_ids = sorted(entry["coupon_id"] for entry in entries)
    order_ids = sorted({entry["order_id"] for entry in entries})
    raw_order_ids = sorted({entry["raw_order_id"] for entry in entries})
    dependencies = {model.__tablename__: _rows(session, model.__table__) for model in CONFIG_MODELS}
    dependencies["orders"] = _rows(session, m.RawDouyinOrder.__table__, or_(
        m.RawDouyinOrder.order_id.in_(order_ids), m.RawDouyinOrder.id.in_(raw_order_ids)))
    # Receipt attribution counts every sibling, including an internal-reference
    # mismatch. Both identity axes must therefore participate in the digest.
    dependencies["coupons_and_siblings"] = _rows(session, m.RawDouyinOrderCoupon.__table__, or_(
        m.RawDouyinOrderCoupon.order_id.in_(order_ids), m.RawDouyinOrderCoupon.raw_order_id.in_(raw_order_ids),
        m.RawDouyinOrderCoupon.coupon_id.in_(coupon_ids)))
    dependencies["verifications"] = _rows(session, m.RawDouyinVerifyRecord.__table__,
                                         m.RawDouyinVerifyRecord.coupon_id.in_(coupon_ids))
    dependencies["raw_refunds"] = _rows(session, m.RawDouyinRefundRecord.__table__,
                                       m.RawDouyinRefundRecord.order_id.in_(order_ids))
    dependencies["refund_events"] = _rows(session, m.DouyinRefundEvent.__table__, or_(
        m.DouyinRefundEvent.coupon_id.in_(coupon_ids), m.DouyinRefundEvent.order_id.in_(order_ids)))
    dependencies["attribution_decisions"] = _rows(session, m.HistoricalSaleAttributionDecision.__table__,
                                                m.HistoricalSaleAttributionDecision.coupon_id.in_(coupon_ids))
    for model in HISTORY_MODELS:
        dependencies[model.__tablename__] = _rows(session, model.__table__, model.coupon_id.in_(coupon_ids))
    sources = m.SettlementCarryforwardSource
    applications = m.SettlementCarryforwardApplication
    dependencies[applications.__tablename__] = _rows(session, applications.__table__,
        applications.carryforward_source_id.in_(select(sources.carryforward_source_id).where(sources.coupon_id.in_(coupon_ids))))
    slots = sorted({(entry[field], entry["business_month"]) for entry in entries
                    for field in ("expected_sale_store_id", "expected_verify_store_id")})
    statements = _rows(session, m.SettlementStatement.__table__,
                       tuple_(m.SettlementStatement.store_id, m.SettlementStatement.statement_month).in_(slots))
    dependencies[m.SettlementStatement.__tablename__] = statements
    dependencies[m.SettlementStatementConfirmation.__tablename__] = _rows(
        session, m.SettlementStatementConfirmation.__table__,
        m.SettlementStatementConfirmation.statement_id.in_([row["statement_id"] for row in statements]))
    for model in (m.SettlementDispute, m.InvoiceRecord, m.PromotionInvoiceAllocation):
        dependencies[model.__tablename__] = _rows(session, model.__table__,
            tuple_(model.store_id, model.statement_month).in_(slots))
    return dependencies


def _assert_eligible(session: Session, manifest: dict, dependencies: dict, started: float) -> tuple[NewFeeQuote, ...]:
    from apps.worker import settlement as s
    for model in HISTORY_MODELS:
        if dependencies[model.__tablename__]:
            raise MissingFeeRepairError("any existing fee/pointer/adjustment/carryforward/entry history rejects whole batch")
    if dependencies[m.SettlementCarryforwardApplication.__tablename__]:
        raise MissingFeeRepairError("carryforward application history rejects whole batch")
    if dependencies["raw_refunds"] or dependencies["refund_events"]:
        raise MissingFeeRepairError("any refund evidence rejects initial missing-only repair")
    quotes = []
    checked_slots = set()
    for entry in sorted(manifest["coupons"], key=lambda row: row["coupon_id"]):
        _budget(started)
        coupon = session.get(m.RawDouyinOrderCoupon, entry["raw_coupon_id"])
        order = session.get(m.RawDouyinOrder, entry["raw_order_id"])
        if (coupon is None or order is None or coupon.coupon_id != entry["coupon_id"]
                or coupon.order_id != entry["order_id"] or order.order_id != entry["order_id"]
                or coupon.raw_order_id != order.id):
            raise MissingFeeRepairError("exact raw/business identity mismatch")
        if (s._dual_order_status(order) != "paid" or s._coupon_refunded_amount(coupon)
                or coupon.latest_refund_at or coupon.coupon_refund_time
                or s._normalized(coupon.coupon_status_normalized or coupon.coupon_status) in s.REFUND_EXCLUDED_STATUSES):
            raise MissingFeeRepairError("refund/cancellation/unknown status rejects whole batch")
        verifications = list(session.scalars(select(m.RawDouyinVerifyRecord).where(
            m.RawDouyinVerifyRecord.coupon_id == coupon.coupon_id)))
        if (len(verifications) != 1 or verifications[0].verify_id != entry["verify_id"]
                or verifications[0].cancel_time is not None
                or s._normalized(verifications[0].verify_status) not in s.VALID_VERIFY_STATUSES
                or canonical(verifications[0].verify_time) != canonical(_instant(entry["verify_time"]))):
            raise MissingFeeRepairError("verification identity/cancellation/multiple verification rejects whole batch")
        for field in ("expected_sale_store_id", "expected_verify_store_id"):
            store_id, month = entry[field], entry["business_month"]
            if (store_id, month) in checked_slots:
                continue
            checked_slots.add((store_id, month))
            # Include stale historical bills and orphan dispute/invoice facts,
            # even where there is no current statement for the slot.
            bills = list(session.scalars(select(m.SettlementStatement).where(
                m.SettlementStatement.store_id == store_id, m.SettlementStatement.statement_month == month)))
            if bills and sum(bool(bill.is_current) for bill in bills) != 1:
                raise MissingFeeRepairError("stale history without one current bill rejects target slot")
            from apps.worker.protected_billing_authority import is_protected_statement
            if any(is_protected_statement(session, bill) for bill in bills):
                raise MissingFeeRepairError("protected target slot rejects whole batch")
            for model in (m.SettlementDispute, m.InvoiceRecord, m.PromotionInvoiceAllocation):
                if session.scalar(select(model.id).where(model.store_id == store_id,
                                                        model.statement_month == month).limit(1)) is not None:
                    raise MissingFeeRepairError("protected target slot has dispute/invoice facts")
        for direction in (s.PROMOTION_FEE, s.MANAGEMENT_FEE):
            quote = quote_new_fee(session, coupon=coupon, order=order, direction=direction)
            if (quote.original_business_month != entry["business_month"]
                    or quote.sale_store_id != entry["expected_sale_store_id"]
                    or quote.qualifying_verify_store_id != entry["expected_verify_store_id"]
                    or quote.qualifying_verify_id != entry["verify_id"]):
                raise MissingFeeRepairError("quoted month/store/verification differs from approved identity")
            quotes.append(quote)
    return tuple(quotes)


def _preview(session: Session, request: dict, started: float) -> tuple[dict, tuple[NewFeeQuote, ...]]:
    dependencies = _source_dependencies(session, request["manifest"]["coupons"])
    quotes = _assert_eligible(session, request["manifest"], dependencies, started)
    quote_rows = canonical([asdict(quote) for quote in quotes])
    dependency_hash = digest(dependencies)
    preview_hash = digest({"request": request, "dependencies": dependency_hash, "quotes": quote_rows})
    _budget(started)
    return {"operation": OPERATION, "request_hash": digest(request), "preview_hash": preview_hash,
            "dependency_hash": dependency_hash, "budget": dict(BUDGET),
            "coupon_count": len(request["manifest"]["coupons"]), "quotes": quote_rows,
            "applied": False, "replayed": False}, quotes


def preview_missing_fees(session: Session, *, manifest: dict, exclusions: dict) -> dict:
    """SELECT-only preview; caller supplies a clean fresh session."""
    request = validate_request(manifest, exclusions)
    _fresh(session)
    with session.begin(), session.no_autoflush:
        if session.get_bind().dialect.name == "postgresql":
            # Driver transaction characteristics preserve the strict SELECT-only
            # SQL surface while making multi-query dependency/quote reads atomic.
            session.connection(execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True})
        report, _ = _preview(session, request, time.monotonic())
        return report


def _fresh(session: Session) -> None:
    if session.in_transaction() or session.new or session.dirty or session.deleted:
        raise MissingFeeRepairError("use a fresh clean session; operation owns its transaction")


def _financial_table_names(session: Session) -> tuple[str, ...]:
    """Include sidecar publication relations outside the ORM's metadata too."""
    prefixes = ("settlement_", "invoice_", "promotion_invoice", "finance_", "store_finance", "management_", "sap_",
                "dashboard_", "agg_store_")
    names = session.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema() ORDER BY tablename"))
    return tuple(name for name in names if (name.startswith(prefixes) or name == m.JobRun.__tablename__)
                 and name != "dashboard_publication_source_counters")


@contextmanager
def _transaction_deadline(session: Session, started: float):
    """Clamp every statement to the remaining wall budget, including flushes."""
    connection = session.connection()
    def before_execute(_conn, cursor, statement, _parameters, _context, _executemany):
        _budget(started)
        # Isolation must be set before any other transaction SQL. Every later
        # SQL statement receives the smaller of 5 seconds and time remaining.
        if statement.upper().startswith("SET TRANSACTION ISOLATION"):
            return
        remaining_ms = int((BUDGET["transaction_wall_seconds"] - (time.monotonic() - started)) * 1000)
        if remaining_ms < BUDGET["statement_timeout_ms"]:
            # The transaction already has a five-second statement timeout.
            # Only its final five seconds need a smaller value; avoid adding
            # an otherwise redundant database roundtrip to every short SELECT.
            cursor.execute(f"SET LOCAL statement_timeout = '{max(1, remaining_ms)}ms'")
    event.listen(connection, "before_cursor_execute", before_execute)
    try:
        yield
    finally:
        event.remove(connection, "before_cursor_execute", before_execute)


def _fence(session: Session, started: float) -> None:
    session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
    session.execute(text("SET LOCAL lock_timeout = '1s'"))
    session.execute(text("SET LOCAL statement_timeout = '5s'"))
    if not session.scalar(select(func.pg_try_advisory_xact_lock(HEAVY_SYNC_CLAIM_LOCK_KEY))):
        raise MissingFeeRepairError("source writer claim lock busy")
    # SHARE ROW EXCLUSIVE conflicts with all DML and self-serializes repairs.
    # Ordered relation fences prevent insert/changed-match phantoms in config,
    # raw evidence, protection facts, and the outside-financial fingerprint.
    tables = {model.__tablename__ for model in CONFIG_MODELS + HISTORY_MODELS + SLOT_MODELS}
    tables.update(_financial_table_names(session))
    tables.update(model.__tablename__ for model in (
        m.RawDouyinOrder, m.RawDouyinOrderCoupon, m.RawDouyinVerifyRecord,
        m.RawDouyinRefundRecord, m.DouyinRefundEvent, m.HistoricalSaleAttributionDecision,
        m.SettlementCarryforwardApplication, m.JobRun, m.FinanceOperationAudit))
    tables.add("dashboard_publication_source_counters")
    session.execute(text("LOCK TABLE " + ", ".join('"' + name.replace('"', '""') + '"' for name in sorted(tables))
                         + " IN SHARE ROW EXCLUSIVE MODE"))
    busy = session.scalar(select(m.JobRun.job_id).where(
        m.JobRun.status.in_(("running", "retry_wait")),
        or_(m.JobRun.execution_slot == "heavy_sync",
            m.JobRun.job_kind.in_(("date_sync", "parent_sync", "finalize", "product_sync")),
            m.JobRun.job_name.in_(("product_sync", "collect_and_settle", "settlement_rebuild", "manual_sync",
                                  "collect_once", "manual_backend_aweme_export", "settlement_compaction",
                                  "refund_evidence_replay"))),
    ).limit(1))
    if busy:
        raise MissingFeeRepairError("source writer running or awaiting retry")
    _budget(started)


def _outside_financial_fingerprint(session: Session, coupon_ids: list[str]) -> str:
    """Server-side row digests keep raw financial tables out of process memory."""
    hashes = {}
    for table_name in _financial_table_names(session):
        where = ""
        params = {}
        if table_name in {m.SettlementFeeResult.__tablename__, m.SettlementFeeResultCurrent.__tablename__}:
            where = " WHERE NOT (t.coupon_id = ANY(:coupon_ids))"
            params["coupon_ids"] = coupon_ids
        # Names originate exclusively in catalog evidence, never manifests.
        statement = "SELECT encode(sha256(convert_to(COALESCE(string_agg(row_hash,'' ORDER BY row_hash),''),'UTF8')),'hex') FROM ("
        statement += "SELECT encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') AS row_hash FROM \""
        statement += table_name.replace('"', '""') + '" t' + where + ') rows'
        hashes[table_name] = session.scalar(text(statement), params)
    hashes["unrelated_source_counters"] = session.scalar(text(
        "SELECT encode(sha256(convert_to(COALESCE(string_agg(encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex'),"
        "'' ORDER BY source_name),''),'UTF8')),'hex') "
        "FROM dashboard_publication_source_counters t "
        "WHERE source_name NOT IN ('settlement_fee_result','settlement_fee_result_current')"))
    return digest(hashes)


def _actual_outputs(session: Session, coupon_ids: list[str], *, calculation_run_id: str) -> list[dict]:
    rows = list(session.scalars(select(m.SettlementFeeResult).where(
        m.SettlementFeeResult.coupon_id.in_(coupon_ids)).order_by(
            m.SettlementFeeResult.coupon_id, m.SettlementFeeResult.fee_direction)))
    if len(rows) != 2 * len(coupon_ids):
        raise MissingFeeRepairError("output count/history mismatch")
    for row in rows:
        pointer = session.scalar(select(m.SettlementFeeResultCurrent).where(
            m.SettlementFeeResultCurrent.coupon_id == row.coupon_id,
            m.SettlementFeeResultCurrent.fee_direction == row.fee_direction))
        if (row.calculation_run_id != calculation_run_id or row.result_version != 1
                or pointer is None or pointer.fee_result_id != row.fee_result_id):
            raise MissingFeeRepairError("actual output/current-pointer identity mismatch")
    return canonical([{field: getattr(row, field) for field in NewFeeQuote.__dataclass_fields__} for row in rows])


def apply_missing_fees(session: Session, *, manifest: dict, exclusions: dict, preview_hash: str) -> dict:
    """Atomically apply an exact reviewed quote on PostgreSQL, or reject all."""
    from apps.worker import settlement as s
    request = validate_request(manifest, exclusions)
    _fresh(session)
    if session.get_bind().dialect.name != "postgresql":
        raise MissingFeeRepairError("apply requires PostgreSQL")
    if not isinstance(preview_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", preview_hash):
        raise MissingFeeRepairError("apply requires exact preview hash")
    started = time.monotonic()
    audit_id = "missing-fee-" + digest(manifest["request_id"])
    calculation_run_id = audit_id
    coupon_ids = sorted(entry["coupon_id"] for entry in manifest["coupons"])
    with session.begin(), session.no_autoflush, _transaction_deadline(session, started):
        _fence(session, started)
        replay = session.scalar(select(m.FinanceOperationAudit).where(m.FinanceOperationAudit.audit_id == audit_id))
        if replay is not None:
            stored = replay.after_snapshot or {}
            if (replay.operation_type != OPERATION or replay.request_payload_sha256 != digest(request)
                    or stored.get("preview_hash") != preview_hash):
                raise MissingFeeRepairError("idempotency request/exclusion/hash mismatch")
            actual = _actual_outputs(session, coupon_ids, calculation_run_id=calculation_run_id)
            if actual != stored.get("quotes"):
                raise MissingFeeRepairError("idempotency actual outputs changed")
            _budget(started)
            return {**stored, "replayed": True}
        # Sorted coupon locks precede all sorted slot locks, then every source
        # is read afresh under the relation fences and READ COMMITTED snapshot.
        list(session.scalars(select(m.RawDouyinOrderCoupon).where(
            m.RawDouyinOrderCoupon.coupon_id.in_(coupon_ids)).order_by(m.RawDouyinOrderCoupon.coupon_id).with_for_update()))
        for store_id, month in sorted({(entry[field], entry["business_month"]) for entry in manifest["coupons"]
                                      for field in ("expected_sale_store_id", "expected_verify_store_id")}):
            s._lock_settlement_slot(session, store_id, month)
        session.expire_all()
        report, _ = _preview(session, request, started)
        if report["preview_hash"] != preview_hash:
            raise MissingFeeRepairError("preview dependency/quote hash changed; whole batch rejected")
        before = _outside_financial_fingerprint(session, coupon_ids)
        _budget(started)
        stats = s.rebuild_dual_fee_results(session, calculation_run_id=calculation_run_id,
                                          coupon_ids=coupon_ids, force_recalculate=False,
                                          progress_callback=lambda *_: _budget(started))
        if (stats.result_count, stats.adjustment_count, stats.blocked_count) != (2 * len(coupon_ids), 0, 0):
            raise MissingFeeRepairError("unexpected result/adjustment/blocked count; whole batch rolled back")
        actual = _actual_outputs(session, coupon_ids, calculation_run_id=calculation_run_id)
        if actual != report["quotes"]:
            raise MissingFeeRepairError("created business fields/input fingerprint differ from quote")
        after = _outside_financial_fingerprint(session, coupon_ids)
        if before != after:
            raise MissingFeeRepairError("outside financial state changed; whole batch rolled back")
        report.update(applied=True, financial_before=before, financial_after=after,
                      calculation_run_id=calculation_run_id)
        session.add(m.FinanceOperationAudit(
            audit_id=audit_id, operation_type=OPERATION, target_type="EXACT_COUPON_BATCH",
            target_id=digest(coupon_ids), operator_id=manifest["actor"], operator_role=1,
            before_snapshot={"financial_fingerprint": before, "coupon_count": len(coupon_ids)},
            after_snapshot=report, result_status=1, request_id=manifest["request_id"],
            idempotency_key_hash=digest({"operation": OPERATION, "request_id": manifest["request_id"]}),
            request_payload_sha256=digest(request),
        ))
        session.flush()
        _budget(started)
        return report
