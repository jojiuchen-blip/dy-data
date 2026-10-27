"""Correct one reviewed historical attachment cohort without rewriting fee facts.

The caller owns commit/rollback. Preview performs no writes. Apply uses the same
slot locks as settlement and creates adjustments plus immutable bill versions.
This deliberately rejects protected or complex slots instead of carrying them
to a different month. Source documents and manifests are private inputs.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
from typing import Any

from sqlalchemy import inspect, or_, select, text
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    FinanceOperationAudit, InvoiceRecord, PromotionInvoiceAllocation,
    SettlementCarryforwardApplication, SettlementCarryforwardSource,
    SettlementDispute, SettlementFeeAdjustment, SettlementFeeResult,
    SettlementFeeResultCurrent, SettlementStatement, SettlementStatementConfirmation,
    SettlementStatementEntry, SettlementStatementLine,
)
from apps.worker.settlement import _apply_and_validate_statement_totals, _lock_settlement_slot

OPERATION = "HISTORICAL_ATTACHMENT_CORRECTION"
TARGET_TYPE = "SETTLEMENT_FEE_RESULT"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MONTH = re.compile(r"20\d{2}-(?:0[1-9]|1[0-2])\Z")
_ROW_TEXT = (
    "order_id", "coupon_id", "store_id", "business_month", "posting_month",
    "expected_fee_result_id", "expected_statement_id", "expected_entry_id",
    "source_sha256", "source_coupon_code", "source_row_sha256",
)
_ROW_INTS = (
    "fee_direction", "expected_statement_version", "old_fee_cent", "target_fee_cent",
    "source_table_index", "source_row",
)
_TIMES = {"created_at", "updated_at"}


class HistoricalFeeCorrectionError(ValueError):
    """Reviewed evidence or financial state cannot safely be corrected."""


def _normal(value: Any) -> Any:
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, dict):
        return {key: _normal(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normal(item) for item in value]
    return value


def evidence_sha256(value: Any) -> str:
    """Hash canonical private manifest/source-row evidence (not a file hash)."""
    return hashlib.sha256(json.dumps(_normal(value), sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _id(prefix: str, *parts: str) -> str:
    return prefix + "-" + evidence_sha256(parts)[:48]


def _model(row: Any) -> dict[str, Any]:
    return _normal({prop.key: getattr(row, prop.key) for prop in inspect(type(row)).column_attrs})


def _copy(row: Any, **overrides: Any) -> Any:
    values = {prop.key: deepcopy(getattr(row, prop.key)) for prop in inspect(type(row)).column_attrs
              if prop.key != "id" and prop.key not in _TIMES}
    return type(row)(**{**values, **overrides})


def _fail(reason: str) -> None:
    raise HistoricalFeeCorrectionError(reason)


def _clean_session(session: Session) -> None:
    if session.new or session.dirty or session.deleted:
        _fail("SESSION_HAS_PENDING_WRITES")


def _validate_manifest(manifest: dict, sources: dict[str, bytes]) -> list[dict]:
    fields = {"schema_version", "request_id", "approved_by", "approval_reference", "rows"}
    if not isinstance(manifest, dict) or set(manifest) != fields or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        _fail("INVALID_MANIFEST")
    for field in ("request_id", "approved_by", "approval_reference"):
        value = manifest[field]
        if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > (500 if field == "approval_reference" else 128):
            _fail("INVALID_APPROVAL_OR_REQUEST")
    rows = manifest["rows"]
    if not isinstance(rows, list) or len(rows) != 16:
        _fail("EXACT_EIGHT_COUPON_SIXTEEN_DIRECTION_SCOPE_REQUIRED")
    documents = {}
    seen = set()
    coupons = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(_ROW_TEXT + _ROW_INTS):
            _fail("INVALID_ROW_FIELDS")
        for field in _ROW_TEXT:
            value = row[field]
            if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 128:
                _fail("INVALID_TEXT_IDENTIFIER")
        if any(type(row[field]) is not int for field in _ROW_INTS):
            _fail("INTEGER_CENTS_AND_VERSIONS_REQUIRED")
        if (row["fee_direction"] not in (1, 2) or row["expected_statement_version"] < 1
                or row["old_fee_cent"] < 0 or row["target_fee_cent"] < 0
                or max(row["old_fee_cent"], row["target_fee_cent"]) > 2**63-1
                or row["source_table_index"] < 0 or row["source_row"] < 2):
            _fail("INVALID_DIRECTION_AMOUNT_OR_VERSION")
        # This approved exception is historical, and cannot select a new month.
        if (not _MONTH.fullmatch(row["business_month"]) or row["business_month"] != "2026-09"
                or row["posting_month"] != row["business_month"]):
            _fail("UNAPPROVED_OR_CROSS_MONTH")
        if not _SHA.fullmatch(row["source_sha256"]) or not _SHA.fullmatch(row["source_row_sha256"]):
            _fail("INVALID_SOURCE_SHA256")
        identity = (row["coupon_id"], row["fee_direction"])
        if identity in seen:
            _fail("DUPLICATE_COUPON_DIRECTION")
        seen.add(identity)
        coupons[row["coupon_id"]].append(row)
        sha = row["source_sha256"]
        if sha not in documents:
            raw = sources.get(sha)
            if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != sha:
                _fail("SOURCE_FILE_SHA256_MISMATCH")
            try:
                documents[sha] = json.loads(raw.decode("utf-8-sig"))
            except (ValueError, UnicodeError) as exc:
                raise HistoricalFeeCorrectionError("INVALID_SOURCE_DOCUMENT") from exc
        try:
            table = documents[sha]["tables"][row["source_table_index"]]
            values = table[row["source_row"] - 1]
            source = dict(zip(table[0], values))
            amount_key = "对应推广费金额" if row["fee_direction"] == 1 else "对应管理服务费金额"
            amount = Decimal(source[amount_key]) * 100
            source_matches = (evidence_sha256(values) == row["source_row_sha256"]
                and source["订单编号"] == row["order_id"]
                and source["券码（已撤销核销加密）"] == row["source_coupon_code"]
                and source["核销时间"][:7] == row["business_month"]
                and amount == row["target_fee_cent"] and amount == amount.to_integral_value())
        except (KeyError, IndexError, TypeError, ValueError, ArithmeticError) as exc:
            raise HistoricalFeeCorrectionError("SOURCE_ROW_INVALID") from exc
        if not source_matches:
            _fail("SOURCE_ROW_DOES_NOT_MATCH_REVIEWED_CORRECTION")
    if len(coupons) != 8:
        _fail("EXACT_EIGHT_COUPON_SCOPE_REQUIRED")
    if len({(pair[0]["source_sha256"],pair[0]["source_table_index"],pair[0]["source_row"])
            for pair in coupons.values()}) != 8:
        _fail("SOURCE_ROW_REUSED_FOR_DIFFERENT_COUPONS")
    for pair in coupons.values():
        if len(pair) != 2 or {row["fee_direction"] for row in pair} != {1, 2}:
            _fail("BOTH_DIRECTIONS_REQUIRED")
        if any(pair[0][field] != pair[1][field] for field in (
            "order_id", "business_month", "source_sha256", "source_table_index", "source_row",
            "source_coupon_code", "source_row_sha256",
        )):
            _fail("COUPON_SOURCE_PAIR_MISMATCH")
    for field in ("expected_fee_result_id", "expected_entry_id"):
        if len({row[field] for row in rows}) != 16:
            _fail("DUPLICATE_REVIEWED_RECORD")
    return sorted(rows, key=lambda row: (row["store_id"], row["posting_month"], row["coupon_id"], row["fee_direction"]))


def _all(session: Session, model: Any, *conditions: Any) -> list:
    return list(session.scalars(select(model).where(*conditions).execution_options(populate_existing=True)))


def _capture(session: Session, rows: list[dict]) -> dict:
    """Read only bounded slots and their full immutable three-layer snapshots."""
    slots = sorted({(row["store_id"], row["posting_month"]) for row in rows})
    fee_ids = [row["expected_fee_result_id"] for row in rows]
    coupon_ids = list({row["coupon_id"] for row in rows})
    bills = _all(session, SettlementStatement, or_(*[
        (SettlementStatement.store_id == store) & (SettlementStatement.statement_month == month)
        for store, month in slots]))
    bill_ids = [bill.statement_id for bill in bills]
    entries = _all(session, SettlementStatementEntry, SettlementStatementEntry.statement_id.in_(bill_ids))
    original_ids = list(set(fee_ids) | {entry.original_fee_result_id for entry in entries})
    state = {
        "bills": bills,
        "lines": _all(session, SettlementStatementLine, SettlementStatementLine.statement_id.in_(bill_ids)),
        "entries": entries,
        "fees": _all(session, SettlementFeeResult, SettlementFeeResult.fee_result_id.in_(fee_ids)),
        "pointers": _all(session, SettlementFeeResultCurrent, SettlementFeeResultCurrent.coupon_id.in_(coupon_ids)),
        "adjustments": _all(session, SettlementFeeAdjustment, or_(
            SettlementFeeAdjustment.original_fee_result_id.in_(original_ids),
            SettlementFeeAdjustment.coupon_id.in_(coupon_ids))),
        "confirmations": _all(session, SettlementStatementConfirmation, SettlementStatementConfirmation.statement_id.in_(bill_ids)),
        "allocations": _all(session, PromotionInvoiceAllocation, or_(*[
            (PromotionInvoiceAllocation.store_id == store) & (PromotionInvoiceAllocation.statement_month == month)
            for store, month in slots])),
        "invoices": _all(session, InvoiceRecord, or_(*[
            (InvoiceRecord.store_id == store) & (InvoiceRecord.statement_month == month)
            for store, month in slots])),
        "disputes": _all(session, SettlementDispute, or_(*[
            (SettlementDispute.store_id == store) & (SettlementDispute.statement_month == month)
            for store, month in slots])),
        "carryforwards": _all(session, SettlementCarryforwardSource, or_(
            SettlementCarryforwardSource.original_fee_result_id.in_(original_ids), *[
                (SettlementCarryforwardSource.store_id == store) & (
                    (SettlementCarryforwardSource.event_month == month)
                    | (SettlementCarryforwardSource.original_business_month == month))
                for store, month in slots])),
        "applications": _all(session, SettlementCarryforwardApplication, SettlementCarryforwardApplication.target_statement_id.in_(bill_ids)),
    }
    return state


def _state_json(state: dict) -> dict:
    return {key: sorted([_model(row) for row in value], key=evidence_sha256) for key,value in state.items()}


def _assert_unprotected(state: dict) -> None:
    for bill in state["bills"]:
        if (bill.statement_status != 2 or bill.confirmed_at or bill.locked_at
                or bill.confirmed_by or bill.locked_by or bill.lock_version):
            _fail("PROTECTED_STATEMENT_SLOT")
    for key in ("confirmations", "allocations", "invoices", "disputes"):
        if state[key]:
            _fail("PROTECTED_" + key.upper())
    if state["carryforwards"] or state["applications"]:
        _fail("COMPLEX_CARRYFORWARD_SLOT")


def _validate_totals(bill: Any, lines: list, entries: list) -> None:
    bill_lines = [line for line in lines if line.statement_id == bill.statement_id]
    bill_entries = [entry for entry in entries if entry.statement_id == bill.statement_id]
    line_map = {line.statement_line_id: line for line in bill_lines}
    if not bill_lines or not bill_entries:
        _fail("INCOMPLETE_BILL_SNAPSHOT")
    for entry in bill_entries:
        line = line_map.get(entry.statement_line_id)
        if line is None or (line.fee_direction, line.product_scope, line.product_type) != (entry.fee_direction, entry.product_scope, entry.product_type):
            _fail("ENTRY_LINE_DIMENSION_MISMATCH")
    for line in bill_lines:
        children = [entry for entry in bill_entries if entry.statement_line_id == line.statement_line_id]
        originals = [entry for entry in children if entry.source_type == 1]
        adjustments = [entry for entry in children if entry.source_type == 2]
        expected = (len(originals),len(adjustments),sum(e.base_amount_cent for e in originals),
                    sum(e.base_amount_cent for e in adjustments),sum(e.fee_amount_cent for e in originals),
                    sum(e.fee_amount_cent for e in adjustments))
        actual = tuple(getattr(line,key) for key in ("original_entry_count","adjustment_entry_count",
            "original_base_cent","adjustment_base_cent","original_fee_cent","adjustment_fee_cent"))
        if actual != expected or line.net_base_cent != expected[2]+expected[3] or line.net_fee_cent != expected[4]+expected[5]:
            _fail("LINE_TOTALS_MISMATCH")
    for direction, prefix in ((1,"promotion"),(2,"management")):
        group = [line for line in bill_lines if line.fee_direction == direction]
        for suffix in ("original_fee_cent","adjustment_fee_cent","net_fee_cent"):
            if getattr(bill,prefix+"_"+suffix) != sum(getattr(line,suffix) for line in group):
                _fail("HEADER_TOTALS_MISMATCH")


def _read_preview(session: Session, manifest: dict, rows: list[dict]) -> tuple[dict, dict]:
    state = _capture(session, rows)
    _assert_unprotected(state)
    if state["adjustments"] or any(entry.source_type != 1 for entry in state["entries"]):
        _fail("EXISTING_ADJUSTMENT_REQUIRES_SEPARATE_REVIEW")
    fees = {fee.fee_result_id:fee for fee in state["fees"]}
    pointers = {(p.coupon_id,p.fee_direction):p.fee_result_id for p in state["pointers"]}
    current = {(bill.store_id,bill.statement_month):bill for bill in state["bills"] if bill.is_current}
    entries = {entry.statement_entry_id:entry for entry in state["entries"]}
    for bill in current.values():
        if bill.version_no != max(other.version_no for other in state["bills"]
                if (other.store_id,other.statement_month) == (bill.store_id,bill.statement_month)):
            _fail("CURRENT_STATEMENT_IS_NOT_LATEST_VERSION")
        _validate_totals(bill,state["lines"],state["entries"])
    for row in rows:
        fee = fees.get(row["expected_fee_result_id"])
        entry = entries.get(row["expected_entry_id"])
        bill = current.get((row["store_id"],row["posting_month"]))
        if (fee is None or pointers.get((row["coupon_id"],row["fee_direction"])) != fee.fee_result_id
                or fee.result_status != 1):
            _fail("CURRENT_FEE_VERSION_CONFLICT")
        store = fee.sale_store_id if row["fee_direction"] == 1 else fee.verify_store_id
        if (fee.order_id,fee.coupon_id,fee.fee_direction,store,fee.original_business_month,fee.fee_amount_cent) != (
            row["order_id"],row["coupon_id"],row["fee_direction"],row["store_id"],row["business_month"],row["old_fee_cent"]):
            _fail("FEE_IDENTITY_OR_OLD_AMOUNT_CONFLICT")
        if (bill is None or bill.statement_id != row["expected_statement_id"]
                or bill.version_no != row["expected_statement_version"]):
            _fail("CURRENT_STATEMENT_VERSION_CONFLICT")
        if (entry is None or (entry.statement_id,entry.source_type,entry.source_record_id,
                entry.original_fee_result_id,entry.order_id,entry.coupon_id,entry.fee_direction,
                entry.original_business_month,entry.statement_posting_month,entry.fee_amount_cent) != (
                bill.statement_id,1,fee.fee_result_id,fee.fee_result_id,row["order_id"],row["coupon_id"],
                row["fee_direction"],row["business_month"],row["posting_month"],row["old_fee_cent"])):
            _fail("ENTRY_IDENTITY_OR_OLD_AMOUNT_CONFLICT")
        if (entry.rule_version != fee.rule_version or entry.base_amount_cent != fee.fee_base_cent
                or entry.product_scope != fee.product_scope or entry.product_type != fee.product_type):
            _fail("ENTRY_FEE_BASIS_CONFLICT")
        responsible_snapshot = entry.sale_store_id_snapshot if row["fee_direction"] == 1 else entry.verify_store_id_snapshot
        if responsible_snapshot != row["store_id"]:
            _fail("ENTRY_RESPONSIBLE_STORE_CONFLICT")
        if sum(e.source_type == 1 and e.source_record_id == fee.fee_result_id and e.statement_id == bill.statement_id
               for e in state["entries"]) != 1:
            _fail("AMBIGUOUS_CURRENT_SOURCE_ENTRY")
    target_entries = {row["expected_entry_id"] for row in rows}
    preview = {
        "request_id":manifest["request_id"], "manifest_sha256":evidence_sha256(manifest),
        "rows":[{**row,"delta_cent":row["target_fee_cent"]-row["old_fee_cent"]} for row in rows],
        "state_sha256":evidence_sha256(_state_json(state)),
        "outside_target_entries_sha256":evidence_sha256(sorted(
            [_model(entry) for entry in state["entries"] if entry.statement_entry_id not in target_entries], key=evidence_sha256)),
        "fee_basis_sha256":evidence_sha256(sorted([_model(fee) for fee in state["fees"]],key=evidence_sha256)),
        "fee_current_pointers_sha256":evidence_sha256(sorted([_model(pointer) for pointer in state["pointers"]],key=evidence_sha256)),
        "changed_statement_ids":sorted({row["expected_statement_id"] for row in rows if row["old_fee_cent"] != row["target_fee_cent"]}),
    }
    preview["preview_sha256"] = evidence_sha256(preview)
    return preview,state


def preview_correction(session: Session, manifest: dict, *, source_documents: dict[str, bytes]) -> dict:
    """Validate the exact eight-coupon scope without flushing or writing any row."""
    _clean_session(session)
    rows = _validate_manifest(manifest,source_documents)
    with session.no_autoflush:
        if _all(session,FinanceOperationAudit,FinanceOperationAudit.operation_type == OPERATION,
                FinanceOperationAudit.request_id == manifest["request_id"]):
            _fail("REQUEST_ALREADY_RECORDED_USE_APPLY_REPLAY")
        preview,_ = _read_preview(session,manifest,rows)
    return preview


def _request_lock(session: Session, request_id: str) -> None:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        if session.connection().get_isolation_level() != "READ COMMITTED":
            _fail("APPLY_REQUIRES_READ_COMMITTED_FOR_POST_LOCK_REVALIDATION")
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                        {"key":"historical-fee-correction:"+request_id})
    elif dialect == "sqlite":
        # Ensure a real outer transaction before SAVEPOINT; rollback must undo it.
        connection = session.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        _fail("UNSUPPORTED_TRANSACTION_DIALECT")


def _replay(session: Session, manifest: dict, rows: list[dict], audits: list, expected_hash: str) -> dict:
    digest = evidence_sha256(manifest)
    if any(a.request_payload_sha256 != digest for a in audits):
        _fail("REQUEST_CONTENT_CONFLICT")
    if len(audits) != len(rows) or {a.target_id for a in audits} != {r["expected_fee_result_id"] for r in rows}:
        _fail("PARTIAL_OR_DUPLICATE_AUDIT")
    if not isinstance(audits[0].after_snapshot,dict):
        _fail("INCOMPLETE_OR_TAMPERED_AUDIT")
    result = audits[0].after_snapshot.get("applied_result")
    if not isinstance(result,dict) or result.get("preview_sha256") != expected_hash:
        _fail("REPLAY_PREVIEW_HASH_CONFLICT")
    for audit in audits:
        if (audit.result_status != 1 or audit.target_type != TARGET_TYPE or not audit.before_snapshot
                or not isinstance(audit.after_snapshot,dict)
                or audit.after_snapshot.get("applied_result") != result
                or audit.after_snapshot.get("evidence_sha256") != evidence_sha256({
                    "before":audit.before_snapshot,
                    "after":{k:v for k,v in audit.after_snapshot.items() if k != "evidence_sha256"}})):
            _fail("INCOMPLETE_OR_TAMPERED_AUDIT")
    state = _capture(session,rows)
    _assert_unprotected(state)
    if evidence_sha256(_state_json(state)) != result["after_state_sha256"]:
        _fail("APPLIED_STATE_CHANGED_OR_PARTIAL")
    return {**result,"already_applied":True}


def _clone_bill(session: Session, bill: Any, state: dict, changes: list[dict], request_id: str) -> str:
    new_id = _id("historical-bill",request_id,bill.statement_id)
    new = _copy(bill,statement_id=new_id,version_no=bill.version_no+1,is_current=False,
                supersedes_statement_id=bill.statement_id,statement_status=2)
    session.add(new)
    line_map = {}
    for line in state["lines"]:
        if line.statement_id == bill.statement_id:
            clone = _copy(line,statement_line_id=_id("historical-line",new_id,line.statement_line_id),statement_id=new_id)
            line_map[line.statement_line_id] = clone
            session.add(clone)
    entry_map = {}
    for entry in state["entries"]:
        if entry.statement_id == bill.statement_id:
            clone = _copy(entry,statement_entry_id=_id("historical-entry",new_id,entry.statement_entry_id),
                          statement_id=new_id,statement_line_id=line_map[entry.statement_line_id].statement_line_id)
            entry_map[entry.statement_entry_id] = clone
            session.add(clone)
    for change in changes:
        source = entry_map[change["expected_entry_id"]]
        line = next(line for line in line_map.values() if line.statement_line_id == source.statement_line_id)
        delta = change["target_fee_cent"]-change["old_fee_cent"]
        adjustment_id = _id("historical-adjustment",request_id,change["expected_fee_result_id"])
        adjustment_entry = _copy(source,
            statement_entry_id=_id("historical-entry",new_id,adjustment_id),source_type=2,
            source_record_id=adjustment_id,base_amount_cent=0,fee_amount_cent=delta,
            adjustment_type_snapshot=4,refund_at_snapshot=None)
        session.add(adjustment_entry)
        line.adjustment_entry_count += 1
        line.adjustment_fee_cent += delta
        line.net_fee_cent += delta
    session.flush()
    _apply_and_validate_statement_totals(session,new)
    bill.is_current = False
    session.flush()
    new.is_current = True
    session.flush()
    return new_id


def apply_correction(session: Session, manifest: dict, *, source_documents: dict[str, bytes],
                     expected_preview_sha256: str) -> dict:
    """Atomically append reviewed deltas and audit all 16 directions; caller commits.

    Protected facts, stale preview, partial prior attempts, conflicting request
    payloads, and unsupported carryforward/adjustment slots fail the whole batch.
    """
    _clean_session(session)
    rows = _validate_manifest(manifest,source_documents)
    if not isinstance(expected_preview_sha256,str) or not _SHA.fullmatch(expected_preview_sha256):
        _fail("EXPECTED_PREVIEW_HASH_REQUIRED")
    _request_lock(session,manifest["request_id"])
    slots = sorted({(row["store_id"],row["posting_month"]) for row in rows})
    for store,month in slots:
        _lock_settlement_slot(session,store,month)
        session.scalar(select(SettlementStatement).where(SettlementStatement.store_id == store,
            SettlementStatement.statement_month == month,SettlementStatement.is_current.is_(True))
            .with_for_update().execution_options(populate_existing=True))
    with session.begin_nested():
        audits = _all(session,FinanceOperationAudit,FinanceOperationAudit.operation_type == OPERATION,
                      FinanceOperationAudit.request_id == manifest["request_id"])
        if audits:
            return _replay(session,manifest,rows,audits,expected_preview_sha256)
        preview,state = _read_preview(session,manifest,rows)
        if preview["preview_sha256"] != expected_preview_sha256:
            _fail("PREVIEW_STATE_CHANGED")
        if _all(session,FinanceOperationAudit,FinanceOperationAudit.operation_type == OPERATION,
                FinanceOperationAudit.target_id.in_([row["expected_fee_result_id"] for row in rows])):
            _fail("FEE_BASIS_ALREADY_CORRECTED")
        now = datetime.now(timezone.utc)
        fee_map = {fee.fee_result_id:fee for fee in state["fees"]}
        entry_map = {entry.statement_entry_id:entry for entry in state["entries"]}
        grouped = defaultdict(list)
        adjustment_ids = []
        for row in rows:
            delta = row["target_fee_cent"]-row["old_fee_cent"]
            if not delta:
                continue
            adjustment_id = _id("historical-adjustment",manifest["request_id"],row["expected_fee_result_id"])
            fee = fee_map[row["expected_fee_result_id"]]
            session.add(SettlementFeeAdjustment(adjustment_id=adjustment_id,
                original_fee_result_id=fee.fee_result_id,refund_event_id=None,coupon_id=fee.coupon_id,
                order_id=fee.order_id,fee_direction=fee.fee_direction,
                original_business_month=fee.original_business_month,adjustment_posting_month=row["posting_month"],
                adjustment_type=4,adjustment_base_cent=0,adjustment_fee_cent=delta,rule_version=fee.rule_version,
                adjustment_reason="历史附件金额纠错；"+manifest["approval_reference"],
                occurred_at=now,created_by=manifest["approved_by"]))
            adjustment_ids.append(adjustment_id)
            grouped[row["expected_statement_id"]].append(row)
        new_bills = {}
        for bill in sorted(state["bills"],key=lambda bill:(bill.store_id,bill.statement_month,bill.version_no)):
            if bill.statement_id in grouped:
                new_bills[bill.statement_id] = _clone_bill(session,bill,state,grouped[bill.statement_id],manifest["request_id"])
        session.flush()
        after_state = _capture(session,rows)
        target_entry_ids = {row["expected_entry_id"] for row in rows}
        outside_ids = {entry.statement_entry_id for entry in state["entries"]}-target_entry_ids
        outside_after = evidence_sha256(sorted([_model(entry) for entry in after_state["entries"]
            if entry.statement_entry_id in outside_ids],key=evidence_sha256))
        fee_after = evidence_sha256(sorted([_model(fee) for fee in after_state["fees"]],key=evidence_sha256))
        if (outside_after != preview["outside_target_entries_sha256"] or fee_after != preview["fee_basis_sha256"]
                or evidence_sha256(sorted([_model(p) for p in after_state["pointers"]],key=evidence_sha256))
                != preview["fee_current_pointers_sha256"]):
            _fail("TARGET_OUTSIDE_SOURCE_OR_FEE_BASIS_CHANGED")
        result = {
            "request_id":manifest["request_id"],"manifest_sha256":evidence_sha256(manifest),
            "preview_sha256":expected_preview_sha256,"adjustment_ids":sorted(adjustment_ids),
            "new_statement_ids":new_bills,
            "unchanged_statement_ids":sorted({row["expected_statement_id"] for row in rows}-set(new_bills)),
            "delta_totals_cent":{str(direction):sum(row["target_fee_cent"]-row["old_fee_cent"] for row in rows
                                                    if row["fee_direction"] == direction) for direction in (1,2)},
            "outside_target_entries_sha256":outside_after,"fee_basis_sha256":fee_after,
            "after_state_sha256":evidence_sha256(_state_json(after_state)),
        }
        for row in rows:
            fee_id = row["expected_fee_result_id"]
            before = {"fee_result":_model(fee_map[fee_id]),"statement_entry":_model(entry_map[row["expected_entry_id"]])}
            delta = row["target_fee_cent"]-row["old_fee_cent"]
            after = {**row,"delta_cent":delta,"manifest_sha256":result["manifest_sha256"],
                "approved_by":manifest["approved_by"],"approval_reference":manifest["approval_reference"],
                "adjustment_id":_id("historical-adjustment",manifest["request_id"],fee_id) if delta else None,
                "applied_result":deepcopy(result)}
            after["evidence_sha256"] = evidence_sha256({"before":before,"after":after})
            session.add(FinanceOperationAudit(audit_id=_id("historical-correction-audit",manifest["request_id"],fee_id),
                operation_type=OPERATION,target_type=TARGET_TYPE,target_id=fee_id,
                operator_id=manifest["approved_by"],operator_role=1,before_snapshot=before,after_snapshot=after,
                result_status=1,request_id=manifest["request_id"],
                idempotency_key_hash=evidence_sha256([OPERATION,manifest["request_id"],fee_id]),
                request_payload_sha256=result["manifest_sha256"],occurred_at=now))
        session.flush()
    return {**result,"already_applied":False}
