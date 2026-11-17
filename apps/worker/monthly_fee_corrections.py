"""Append exact reviewed fee deltas to the processing month."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from apps.api.dy_api.models import (
    FinanceOperationAudit, RawDouyinOrderCoupon, SettlementDispute, SettlementDisputeOrder,
    SettlementFeeAdjustment, SettlementFeeResult,
    SettlementStatement, SettlementStatementEntry, SettlementStatementVisibility, utcnow,
)
from apps.worker.historical_fee_correction import (
    HistoricalFeeCorrectionError, _SHA, _clean_session, _request_lock, evidence_sha256,
)
from apps.worker.missing_fee_repair import NewFeeQuote, NewFeeQuoteError
from apps.worker.protected_billing_authority import is_protected_statement
from apps.worker.settlement import (
    SUPERSEDED_FEE_RESULT, _business_month, _effective_adjustment_totals, _lock_settlement_slot, _materialize_dual_fee_direction,
    _raw_order_for_coupon, _stable_business_id,
)


OPERATION = "PROCESSING_MONTH_FEE_CORRECTION"
TARGET_TYPE = "SETTLEMENT_FEE_ADJUSTMENT"
REQUIRED_FIELDS = {
    "case_id", "coupon_id", "order_id", "store_id", "fee_direction", "original_statement_id",
    "original_statement_version", "original_business_month", "original_entry_id",
    "expected_fee_cent", "corrected_fee_cent", "evidence_sha256",
}


def approved_month_correction_condition(adjustment_id):
    return select(FinanceOperationAudit.id).where(
        FinanceOperationAudit.operation_type == OPERATION,
        FinanceOperationAudit.target_type == TARGET_TYPE,
        FinanceOperationAudit.target_id == adjustment_id,
        FinanceOperationAudit.result_status == 1,
    ).exists()


def reviewed_fee_basis_condition(original_fee_result_id):
    """A missed-fee basis and its later real refunds share one reviewed authority."""
    adjustment = aliased(SettlementFeeAdjustment)
    return select(adjustment.id).where(
        adjustment.original_fee_result_id == original_fee_result_id,
        approved_month_correction_condition(adjustment.adjustment_id),
    ).exists()


def has_processing_month_correction(session: Session, fee_result_id: str) -> bool:
    return bool(session.scalar(select(reviewed_fee_basis_condition(fee_result_id))))


def missed_coupon_correction_basis(
    session: Session, *, coupon_id: str, direction: int,
) -> SettlementFeeResult | None:
    # Do not recover an unreviewed non-current calculation as financial basis.
    basis_id = _stable_business_id("missed-fee-correction-basis", coupon_id, str(direction))
    return session.scalar(select(SettlementFeeResult).where(
        SettlementFeeResult.fee_result_id == basis_id,
        reviewed_fee_basis_condition(SettlementFeeResult.fee_result_id),
    ))


def _clean_text(value: Any, *, limit: int = 128) -> bool:
    return isinstance(value, str) and bool(value) and value.strip() == value and len(value) <= limit


def _validate(manifest: dict, evidence: dict[str, bytes]) -> list[dict]:
    required = {"request_id", "processing_month", "rows", "schema_version"}
    if (not isinstance(manifest, dict)
            or (set(manifest) - {"dispute_id"}) != required
            or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or not _clean_text(manifest["request_id"])
            or ("dispute_id" in manifest and not _clean_text(manifest["dispute_id"]))):
        raise HistoricalFeeCorrectionError("INVALID_MONTHLY_CORRECTION_MANIFEST")
    rows = manifest["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise HistoricalFeeCorrectionError("EXACT_BOUNDED_CORRECTION_SCOPE_REQUIRED")
    for row in rows:
        if not isinstance(row, dict) or set(row) != REQUIRED_FIELDS:
            raise HistoricalFeeCorrectionError("INVALID_CORRECTION_ROW_FIELDS")
        if not all(_clean_text(row[field]) for field in (
            "case_id", "coupon_id", "order_id", "store_id", "original_statement_id", "original_business_month",
        )) or (row["original_entry_id"] is not None and not _clean_text(row["original_entry_id"])):
            raise HistoricalFeeCorrectionError("INVALID_CORRECTION_IDENTIFIER")
        month = row["original_business_month"]
        try:
            parsed = date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise HistoricalFeeCorrectionError("INVALID_ORIGINAL_MONTH") from exc
        if parsed.strftime("%Y-%m") != month or month < "2026-08":
            raise HistoricalFeeCorrectionError("INVALID_ORIGINAL_MONTH")
        if (type(row["fee_direction"]) is not int or row["fee_direction"] not in (1, 2)
                or type(row["original_statement_version"]) is not int or row["original_statement_version"] < 1
                or any(type(row[name]) is not int or not 0 <= row[name] <= 2**63-1
                       for name in ("expected_fee_cent", "corrected_fee_cent"))
                or row["expected_fee_cent"] == row["corrected_fee_cent"]):
            raise HistoricalFeeCorrectionError("INVALID_CORRECTION_VERSION_DIRECTION_OR_AMOUNT")
        source_sha = row["evidence_sha256"]
        if not isinstance(source_sha, str) or not _SHA.fullmatch(source_sha):
            raise HistoricalFeeCorrectionError("INVALID_CORRECTION_EVIDENCE_SHA256")
        source = evidence.get(source_sha)
        if not isinstance(source, bytes) or not source or sha256(source).hexdigest() != source_sha:
            raise HistoricalFeeCorrectionError("CORRECTION_EVIDENCE_FILE_MISMATCH")
    if (len({row["case_id"] for row in rows}) != len(rows)
            or len({(row["coupon_id"], row["fee_direction"]) for row in rows}) != len(rows)):
        raise HistoricalFeeCorrectionError("DUPLICATE_REVIEWED_CORRECTION")
    return sorted(rows, key=lambda row: (row["coupon_id"], row["fee_direction"]))


def _audit_id(case_id: str) -> str:
    return _stable_business_id("monthly-fee-correction-audit", case_id)


def _statement(session: Session, row: dict) -> SettlementStatement:
    bill = session.scalar(select(SettlementStatement).where(
        SettlementStatement.statement_id == row["original_statement_id"],
        SettlementStatement.store_id == row["store_id"],
        SettlementStatement.statement_month == row["original_business_month"],
        SettlementStatement.version_no == row["original_statement_version"],
        SettlementStatement.is_current.is_(True),
    ).execution_options(populate_existing=True))
    if bill is None or bill.statement_status < 2:
        raise HistoricalFeeCorrectionError("REVIEWED_ORIGINAL_STATEMENT_CHANGED")
    if (session.get(SettlementStatementVisibility, bill.statement_id) is None
            and not is_protected_statement(session, bill)):
        raise HistoricalFeeCorrectionError("ORIGINAL_STATEMENT_FREEZE_NOT_PROVEN")
    return bill


def _correction_basis(
    session: Session, *, row: dict, bill: SettlementStatement
) -> tuple[SettlementFeeResult | NewFeeQuote, int, str]:
    direction = row["fee_direction"]
    entries = list(session.scalars(select(SettlementStatementEntry).where(
        SettlementStatementEntry.statement_id == bill.statement_id,
        SettlementStatementEntry.coupon_id == row["coupon_id"],
        SettlementStatementEntry.fee_direction == direction,
    ).order_by(SettlementStatementEntry.statement_entry_id)))
    if any(entry.order_id != row["order_id"] for entry in entries):
        raise HistoricalFeeCorrectionError("ORIGINAL_COUPON_ORDER_MISMATCH")
    if row["original_entry_id"] is None:
        if entries or row["expected_fee_cent"] != 0:
            raise HistoricalFeeCorrectionError("MISSED_COUPON_ALREADY_HAS_ORIGINAL_FEE")
        coupon = session.scalar(select(RawDouyinOrderCoupon).where(
            RawDouyinOrderCoupon.coupon_id == row["coupon_id"],
        ).execution_options(populate_existing=True))
        order = _raw_order_for_coupon(session, coupon) if coupon is not None else None
        if order is None or order.order_id != row["order_id"]:
            raise HistoricalFeeCorrectionError("REVIEWED_COUPON_SOURCE_MISSING")
        try:
            with session.no_autoflush:
                quote = _materialize_dual_fee_direction(
                    session, order=order, coupon=coupon, direction=direction,
                    calculation_run_id="monthly-correction-quote", current=None, quote_only=True,
                    accounting_month=bill.statement_month,
                )
        except NewFeeQuoteError as exc:
            raise HistoricalFeeCorrectionError("MISSED_COUPON_BASIS_NOT_PROVEN") from exc
        if not isinstance(quote, NewFeeQuote):
            raise HistoricalFeeCorrectionError("MISSED_COUPON_BASIS_NOT_PROVEN")
        store_id = quote.sale_store_id if direction == 1 else quote.verify_store_id
        if store_id != bill.store_id or quote.fee_amount_cent != row["corrected_fee_cent"]:
            raise HistoricalFeeCorrectionError("MISSED_COUPON_QUOTE_MISMATCH")
        return quote, 0, evidence_sha256(asdict(quote))

    originals = [entry for entry in entries if entry.source_type == 1]
    if len(originals) != 1 or originals[0].statement_entry_id != row["original_entry_id"]:
        raise HistoricalFeeCorrectionError("ORIGINAL_FEE_ENTRY_CHANGED")
    original = originals[0]
    if any(entry.original_fee_result_id != original.original_fee_result_id for entry in entries):
        raise HistoricalFeeCorrectionError("COMPLEX_COUPON_BASIS_REQUIRES_SEPARATE_REVIEW")
    fee = session.scalar(select(SettlementFeeResult).where(
        SettlementFeeResult.fee_result_id == original.original_fee_result_id,
        SettlementFeeResult.coupon_id == row["coupon_id"], SettlementFeeResult.order_id == row["order_id"],
        SettlementFeeResult.original_business_month == bill.statement_month,
        SettlementFeeResult.fee_direction == direction,
    ))
    store_id = (fee.sale_store_id if direction == 1 else fee.verify_store_id) if fee else None
    if fee is None or store_id != bill.store_id:
        raise HistoricalFeeCorrectionError("ORIGINAL_DIRECTION_STORE_MISMATCH")
    outside_entries = [
        adjustment for adjustment in session.scalars(select(SettlementFeeAdjustment).where(
            SettlementFeeAdjustment.original_fee_result_id == fee.fee_result_id,
            SettlementFeeAdjustment.adjustment_type == 4,
            approved_month_correction_condition(SettlementFeeAdjustment.adjustment_id),
        ).order_by(SettlementFeeAdjustment.adjustment_id))
        if adjustment.adjustment_id not in {entry.source_record_id for entry in entries}
    ]
    amount = sum(entry.fee_amount_cent for entry in entries) + sum(
        adjustment.adjustment_fee_cent for adjustment in outside_entries
    )
    if amount != row["expected_fee_cent"]:
        raise HistoricalFeeCorrectionError("EXPECTED_COUPON_FEE_CHANGED")
    _, existing_delta = _effective_adjustment_totals(session, original_fee_result_id=fee.fee_result_id)
    if fee.fee_amount_cent + existing_delta + row["corrected_fee_cent"] - amount < 0:
        raise HistoricalFeeCorrectionError("CORRECTION_OVERLAPS_EXISTING_REVERSALS")
    snapshot = {
        "entries": [(entry.statement_entry_id, entry.fee_amount_cent) for entry in entries],
        "previous_corrections": [(adjustment.adjustment_id, adjustment.adjustment_fee_cent) for adjustment in outside_entries],
        "fee_result_id": fee.fee_result_id,
    }
    return fee, amount, evidence_sha256(snapshot)


def _dispute_review_scope(session: Session, *, dispute_id: str, rows: list[dict], lock: bool = False) -> dict:
    query = select(SettlementDispute).where(SettlementDispute.dispute_id == dispute_id)
    if lock:
        query = query.with_for_update()
    dispute = session.scalar(query.execution_options(populate_existing=True))
    if dispute is None or dispute.status not in (1, 2, 3) or dispute.result_statement_id:
        raise HistoricalFeeCorrectionError("DISPUTE_NO_LONGER_PENDING")
    if any(
        (row["original_statement_id"], row["store_id"], row["original_business_month"], row["fee_direction"])
        != (dispute.statement_id, dispute.store_id, dispute.statement_month, dispute.fee_direction)
        for row in rows
    ):
        raise HistoricalFeeCorrectionError("CORRECTION_DISPUTE_SCOPE_MISMATCH")
    orders = sorted((row.order_id, row.coupon_id or "") for row in session.scalars(
        select(SettlementDisputeOrder).where(SettlementDisputeOrder.dispute_id == dispute_id)
    ))
    if orders and any(
        (row["order_id"], row["coupon_id"]) not in orders and (row["order_id"], "") not in orders
        for row in rows
    ):
        raise HistoricalFeeCorrectionError("CORRECTION_DISPUTE_COUPON_OUTSIDE_SCOPE")
    if session.scalar(select(FinanceOperationAudit.id).where(
        FinanceOperationAudit.operation_type == OPERATION,
        FinanceOperationAudit.request_id == dispute_id,
        FinanceOperationAudit.result_status == 1,
    ).limit(1)) is not None:
        raise HistoricalFeeCorrectionError("DISPUTE_ALREADY_HAS_APPROVED_CORRECTION")
    return {"dispute_id": dispute_id, "status": dispute.status, "orders": orders}


def _capture(session: Session, rows: list[dict], month: str) -> tuple[list[dict], list]:
    report, basis = [], []
    for row in rows:
        bill = _statement(session, row)
        if bill.statement_month >= month:
            raise HistoricalFeeCorrectionError("PROCESSING_MONTH_MUST_FOLLOW_ORIGINAL")
        if session.scalar(select(SettlementStatement.id).where(
            SettlementStatement.store_id == bill.store_id,
            SettlementStatement.statement_month == month,
            SettlementStatement.is_current.is_(True),
        )) is not None:
            raise HistoricalFeeCorrectionError("PROCESSING_STORE_PERIOD_ALREADY_FROZEN")
        fee, old_amount, fingerprint = _correction_basis(session, row=row, bill=bill)
        report.append({**row, "basis_sha256": fingerprint, "delta_cent": row["corrected_fee_cent"] - old_amount})
        basis.append(fee)
    return report, basis


def preview_monthly_fee_corrections(
    session: Session, manifest: dict, *, evidence: dict[str, bytes], now: datetime | None = None,
) -> dict:
    """Produce an exact immutable business-facts fingerprint without writes."""
    _clean_session(session)
    rows = _validate(manifest, evidence)
    month = _business_month(now or utcnow())
    if manifest["processing_month"] != month:
        raise HistoricalFeeCorrectionError("PROCESSING_MONTH_CHANGED")
    report, _ = _capture(session, rows, month)
    payload = {"request_id": manifest["request_id"], "processing_month": month, "rows": report}
    if "dispute_id" in manifest:
        payload["dispute_scope"] = _dispute_review_scope(session, dispute_id=manifest["dispute_id"], rows=rows)
    return {**payload, "preview_sha256": evidence_sha256(payload)}


def apply_monthly_fee_corrections(
    session: Session, manifest: dict, *, evidence: dict[str, bytes],
    expected_preview_sha256: str, approved_by: str, approval_reference: str,
    now: datetime | None = None,
) -> dict:
    """Append only reviewed deltas in one transaction; commit belongs to caller."""
    _clean_session(session)
    if session.get_bind().dialect.name != "postgresql":
        raise HistoricalFeeCorrectionError("CORRECTION_APPLY_REQUIRES_POSTGRESQL")
    if (not _clean_text(approved_by) or not _clean_text(approval_reference, limit=500)
            or not isinstance(expected_preview_sha256, str) or not _SHA.fullmatch(expected_preview_sha256)):
        raise HistoricalFeeCorrectionError("EXACT_CORRECTION_APPROVAL_REQUIRED")
    rows = _validate(manifest, evidence)
    when = now or utcnow()
    month = _business_month(when)
    manifest_sha = evidence_sha256({**manifest, "rows": rows})
    with session.begin_nested():
        for case_id in sorted(row["case_id"] for row in rows):
            _request_lock(session, f"monthly-fee-case:{case_id}")
        # Share the calculator's coupon-before-slot order.
        for coupon_id in sorted({row["coupon_id"] for row in rows}):
            session.scalar(select(RawDouyinOrderCoupon.id).where(
                RawDouyinOrderCoupon.coupon_id == coupon_id,
            ).with_for_update())
        audits = {row.audit_id: row for row in session.scalars(select(FinanceOperationAudit).where(
            FinanceOperationAudit.audit_id.in_([_audit_id(row["case_id"]) for row in rows]),
        ))}
        if audits:
            if (len(audits) != len(rows) or any(
                audit.request_payload_sha256 != manifest_sha or audit.operator_id != approved_by
                or audit.result_status != 1 or audit.operation_type != OPERATION
                or audit.after_snapshot.get("preview_sha256") != expected_preview_sha256
                or audit.after_snapshot.get("approval_reference") != approval_reference
                or session.scalar(select(SettlementFeeAdjustment.id).where(
                    SettlementFeeAdjustment.adjustment_id == audit.target_id,
                )) is None
                for audit in audits.values()
            )):
                raise HistoricalFeeCorrectionError("CORRECTION_CASE_ALREADY_USED_OR_INCOMPLETE")
            return {"already_applied": True, "adjustment_count": len(rows), "preview_sha256": expected_preview_sha256}

        if manifest["processing_month"] != month:
            raise HistoricalFeeCorrectionError("PROCESSING_MONTH_CHANGED")
        dispute_scope = (
            _dispute_review_scope(session, dispute_id=manifest["dispute_id"], rows=rows, lock=True)
            if "dispute_id" in manifest else None
        )
        slots = {(row["store_id"], row["original_business_month"]) for row in rows}
        slots.update((row["store_id"], month) for row in rows)
        for store_id, slot_month in sorted(slots):
            _lock_settlement_slot(session, store_id, slot_month)
        report, basis = _capture(session, rows, month)
        payload = {"request_id": manifest["request_id"], "processing_month": month, "rows": report}
        if dispute_scope is not None:
            payload["dispute_scope"] = dispute_scope
        if evidence_sha256(payload) != expected_preview_sha256:
            raise HistoricalFeeCorrectionError("EXACT_CORRECTION_PREVIEW_CHANGED")
        for row, fee in zip(report, basis, strict=True):
            adjustment_id = _stable_business_id("processing-month-adjustment", row["case_id"])
            if isinstance(fee, NewFeeQuote):
                # Store verified basis without creating a historical current
                # result or moving the frozen original statement's amount.
                values = asdict(fee)
                values.update(
                    fee_result_id=_stable_business_id("missed-fee-correction-basis", row["coupon_id"], str(row["fee_direction"])),
                    result_status=SUPERSEDED_FEE_RESULT, calculated_at=when,
                    calculation_run_id=_audit_id(row["case_id"]),
                )
                fee = SettlementFeeResult(**values)
                session.add(fee)
                adjustment_id = _stable_business_id("missed-coupon-posting", fee.fee_result_id)
            session.add(SettlementFeeAdjustment(
                adjustment_id=adjustment_id, original_fee_result_id=fee.fee_result_id,
                coupon_id=row["coupon_id"], order_id=row["order_id"], fee_direction=row["fee_direction"],
                original_business_month=row["original_business_month"], adjustment_posting_month=month,
                adjustment_type=4, adjustment_base_cent=0, adjustment_fee_cent=row["delta_cent"],
                rule_version=fee.rule_version, adjustment_reason="核准费用更正，记入处理月。",
                occurred_at=when, created_by=approved_by,
            ))
            session.add(FinanceOperationAudit(
                audit_id=_audit_id(row["case_id"]), operation_type=OPERATION, target_type=TARGET_TYPE,
                target_id=adjustment_id, operator_id=approved_by, operator_role=1, result_status=1,
                request_id=manifest.get("dispute_id") or manifest["request_id"],
                request_payload_sha256=manifest_sha, occurred_at=when,
                before_snapshot={"expected_fee_cent": row["expected_fee_cent"]},
                after_snapshot={**row, "processing_month": month, "preview_sha256": expected_preview_sha256,
                                "approval_reference": approval_reference, "fee_result_id": fee.fee_result_id,
                                "dispute_id": manifest.get("dispute_id")},
            ))
        session.flush()
    return {"already_applied": False, "adjustment_count": len(rows), "preview_sha256": expected_preview_sha256}


def posted_monthly_dispute_statement(
    session: Session, *, dispute: SettlementDispute, adjustment_amount_cent: int,
) -> SettlementStatement | None:
    """Return the exact first-visible processing bill only after every approved delta posted."""
    applied = list(session.scalars(select(FinanceOperationAudit).where(
        FinanceOperationAudit.request_id == dispute.dispute_id,
        FinanceOperationAudit.operation_type == OPERATION, FinanceOperationAudit.result_status == 1,
    )))
    if not applied or any(
        not isinstance(audit.after_snapshot, dict)
        or audit.after_snapshot.get("original_statement_id") != dispute.statement_id
        or audit.after_snapshot.get("dispute_id") != dispute.dispute_id
        for audit in applied
    ):
        return None
    targets = {audit.target_id for audit in applied}
    if len(targets) != len(applied):
        return None
    results = session.execute(
        select(SettlementStatement, SettlementStatementEntry)
        .join(SettlementStatementEntry, SettlementStatementEntry.statement_id == SettlementStatement.statement_id)
        .join(SettlementStatementVisibility, SettlementStatementVisibility.statement_id == SettlementStatement.statement_id)
        .where(
            SettlementStatement.is_current.is_(True), SettlementStatement.store_id == dispute.store_id,
            SettlementStatement.statement_month > dispute.statement_month,
            SettlementStatementEntry.source_type == 2, SettlementStatementEntry.fee_direction == dispute.fee_direction,
            SettlementStatementEntry.source_record_id.in_(targets),
        ),
    ).all()
    if (len(results) != len(targets) or {entry.source_record_id for _, entry in results} != targets
            or len({statement.statement_id for statement, _ in results}) != 1
            or sum(entry.fee_amount_cent for _, entry in results) != adjustment_amount_cent):
        return None
    return results[0][0]
