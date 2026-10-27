"""Synthetic attachment correction: exact scope, snapshots and atomic writes."""
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.models import (
    DimStore, FinanceOperationAudit, InvoiceRecord, PromotionInvoiceAllocation,
    SettlementCarryforwardSource, SettlementDispute, SettlementFeeAdjustment,
    SettlementFeeResult, SettlementFeeResultCurrent, SettlementStatement,
    SettlementStatementConfirmation, SettlementStatementEntry, SettlementStatementLine,
)
from apps.worker import historical_fee_correction as correction

MONTH = "2026-09"
NOW = datetime(2026,10,27,1,tzinfo=timezone.utc)
MODELS = (SettlementFeeResult,SettlementFeeResultCurrent,SettlementFeeAdjustment,
          SettlementStatement,SettlementStatementLine,SettlementStatementEntry,FinanceOperationAudit)


def seed(session,amounts=None):
    """Eight fake coupons with two unchanged and six changed fee amounts."""
    headers = ["订单编号","券码（已撤销核销加密）","核销时间","对应推广费金额","对应管理服务费金额"]
    values = [[f"order-{index}",f"code-{index}","2026-09-12 10:00:00","16.8","16.8"] for index in range(8)]
    raw = json.dumps({"tables":[[headers,*values]]},ensure_ascii=False).encode()
    sha = hashlib.sha256(raw).hexdigest()
    stores = ["sale-store",*[f"verify-store-{index}" for index in range(8)]]
    for store in stores:
        session.add(DimStore(store_id=store,store_name="Synthetic "+store))
        session.add(SettlementStatement(statement_id="bill-"+store,store_id=store,statement_month=MONTH,
            version_no=3,is_current=True,statement_status=2,store_name_snapshot="Frozen "+store,
            sap_code_snapshot="000-synthetic",store_snapshot_status="LIVE_CAPTURED",store_snapshot_profile_id="frozen-profile"))
    rows = []
    for index,amount in enumerate(amounts or [1680,1280,1680,1480,1610,1180,1620,1620]):
        for direction in (1,2):
            store = "sale-store" if direction == 1 else f"verify-store-{index}"
            bill_id = "bill-"+store
            fee_id = f"fee-{index}-{direction}"
            entry_id = "entry-"+fee_id
            session.add(SettlementFeeResult(fee_result_id=fee_id,coupon_id=f"coupon-{index}",
                order_id=f"order-{index}",fee_direction=direction,result_version=2,original_business_month=MONTH,
                rule_match_date=date(2026,9,12),sale_store_id="sale-store",verify_store_id=f"verify-store-{index}",
                sku_id="synthetic-sku",product_scope="scope",product_type="type",sale_channel_normalized="live",
                source_amount_cent=amount*10,fee_base_cent=amount*10,fee_rate=Decimal("0.1"),fee_amount_cent=amount,
                rule_version="rule-frozen",scope_rule_version="scope-rule",result_status=1,
                calculation_run_id="synthetic-run",calculated_at=NOW,qualifying_verify_id=f"verify-{index}",
                qualifying_verify_time=NOW,qualifying_verify_store_id=f"verify-store-{index}"))
            session.add(SettlementFeeResultCurrent(coupon_id=f"coupon-{index}",fee_direction=direction,fee_result_id=fee_id))
            session.add(SettlementStatementEntry(statement_entry_id=entry_id,statement_id=bill_id,
                statement_line_id="line-"+store,source_type=1,source_record_id=fee_id,original_fee_result_id=fee_id,
                coupon_id=f"coupon-{index}",order_id=f"order-{index}",fee_direction=direction,
                original_business_month=MONTH,statement_posting_month=MONTH,product_scope="scope",product_type="type",
                base_amount_cent=amount*10,fee_amount_cent=amount,rule_version="rule-frozen",
                order_status_snapshot="frozen-paid",coupon_status_snapshot="frozen-verified",
                product_name_snapshot="Frozen product",sku_id_snapshot="frozen-sku",sku_name_snapshot="Frozen SKU name",
                sale_channel_snapshot="frozen-channel",sale_store_id_snapshot="sale-store",sale_store_snapshot="Frozen sale",
                verify_store_id_snapshot=f"verify-store-{index}",verify_store_snapshot="Frozen verify",sale_time_snapshot=NOW,
                verify_time_snapshot=NOW,received_amount_cent_snapshot=amount*10,fee_rate_snapshot=Decimal("0.1")))
            rows.append(dict(order_id=f"order-{index}",coupon_id=f"coupon-{index}",fee_direction=direction,store_id=store,
                business_month=MONTH,posting_month=MONTH,expected_fee_result_id=fee_id,expected_statement_id=bill_id,
                expected_statement_version=3,expected_entry_id=entry_id,old_fee_cent=amount,target_fee_cent=1680,
                source_sha256=sha,source_table_index=0,source_row=index+2,source_coupon_code=f"code-{index}",
                source_row_sha256=correction.evidence_sha256(values[index])))
    # An unrelated fee source in the same bill must retain every snapshot field.
    session.add(SettlementStatementEntry(statement_entry_id="outside-entry",statement_id="bill-sale-store",
        statement_line_id="line-sale-store",source_type=1,source_record_id="outside-fee",original_fee_result_id="outside-fee",
        coupon_id="outside-coupon",order_id="outside-order",fee_direction=1,original_business_month=MONTH,
        statement_posting_month=MONTH,product_scope="scope",product_type="type",base_amount_cent=5000,fee_amount_cent=500,
        rule_version="outside-rule",product_name_snapshot="Do not reread mutable raw",refund_at_snapshot=NOW))
    session.flush()
    for store in stores:
        entries = list(session.scalars(select(SettlementStatementEntry).where(SettlementStatementEntry.statement_id == "bill-"+store)))
        base = sum(entry.base_amount_cent for entry in entries)
        fee = sum(entry.fee_amount_cent for entry in entries)
        direction = 1 if store == "sale-store" else 2
        session.add(SettlementStatementLine(statement_line_id="line-"+store,statement_id="bill-"+store,
            fee_direction=direction,product_scope="scope",product_type="type",original_entry_count=len(entries),
            original_base_cent=base,net_base_cent=base,original_fee_cent=fee,net_fee_cent=fee))
        bill = session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "bill-"+store))
        prefix = "promotion" if direction == 1 else "management"
        setattr(bill,prefix+"_original_fee_cent",fee)
        setattr(bill,prefix+"_net_fee_cent",fee)
    session.commit()
    return dict(schema_version=1,request_id="synthetic-request",approved_by="synthetic-admin",
                approval_reference="synthetic-approved-exact-eight",rows=rows),{sha:raw}


@pytest.fixture
def cohort(db_session):
    return seed(db_session)


def fingerprint(session):
    return correction.evidence_sha256({model.__name__:sorted(
        [correction._model(row) for row in session.scalars(select(model))],key=correction.evidence_sha256)
        for model in MODELS})


def apply(session,manifest,sources,preview=None):
    preview = preview or correction.preview_correction(session,manifest,source_documents=sources)
    return correction.apply_correction(session,manifest,source_documents=sources,
                                        expected_preview_sha256=preview["preview_sha256"])


def test_preview_is_read_only_and_expected_hash_covers_full_snapshot(db_session,cohort):
    manifest,sources = cohort
    before = fingerprint(db_session)
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    assert fingerprint(db_session) == before
    assert not db_session.new and not db_session.dirty
    assert len(preview["rows"]) == 16 and len(preview["changed_statement_ids"]) == 7
    assert sum(row["delta_cent"] for row in preview["rows"]) == 2580
    assert len(preview["outside_target_entries_sha256"]) == 64
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="EXPECTED_PREVIEW"):
        correction.apply_correction(db_session,manifest,source_documents=sources,expected_preview_sha256="")
    assert fingerprint(db_session) == before


def test_apply_clones_all_snapshots_only_adds_deltas_and_replays(db_session,cohort):
    manifest,sources = cohort
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    old_entries = {entry.statement_entry_id:correction._model(entry) for entry in db_session.scalars(select(SettlementStatementEntry))}
    old_fees = [correction._model(row) for row in db_session.scalars(select(SettlementFeeResult))]
    old_pointers = [correction._model(row) for row in db_session.scalars(select(SettlementFeeResultCurrent))]
    result = apply(db_session,manifest,sources,preview)
    db_session.commit()
    db_session.expire_all()
    assert len(result["new_statement_ids"]) == 7
    assert len(result["unchanged_statement_ids"]) == 2
    assert len(result["adjustment_ids"]) == 12
    assert result["delta_totals_cent"] == {"1":1290,"2":1290}
    assert result["outside_target_entries_sha256"] == preview["outside_target_entries_sha256"]
    assert result["fee_basis_sha256"] == preview["fee_basis_sha256"]
    assert [correction._model(row) for row in db_session.scalars(select(SettlementFeeResult))] == old_fees
    assert [correction._model(row) for row in db_session.scalars(select(SettlementFeeResultCurrent))] == old_pointers
    assert db_session.scalar(select(func.count()).select_from(FinanceOperationAudit)) == 16
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 16
    for entry_id,original in old_entries.items():
        entry = db_session.scalar(select(SettlementStatementEntry).where(SettlementStatementEntry.statement_entry_id == entry_id))
        assert correction._model(entry) == original
        if original["statement_id"] in result["new_statement_ids"]:
            clone = db_session.scalar(select(SettlementStatementEntry).where(
                SettlementStatementEntry.statement_id == result["new_statement_ids"][original["statement_id"]],
                SettlementStatementEntry.source_record_id == original["source_record_id"],SettlementStatementEntry.source_type == 1))
            values = correction._model(clone)
            for key in original:
                if key not in {"id","statement_entry_id","statement_id","statement_line_id","created_at","updated_at"}:
                    assert values[key] == original[key]
    for old_id,new_id in result["new_statement_ids"].items():
        old = db_session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == old_id))
        new = db_session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == new_id))
        assert not old.is_current and new.is_current and new.version_no == old.version_no+1
        assert new.supersedes_statement_id == old_id
        assert new.statement_status == 2 and new.confirmed_at is None and new.locked_at is None
        assert (new.store_name_snapshot,new.sap_code_snapshot,new.store_snapshot_profile_id) == (
            old.store_name_snapshot,old.sap_code_snapshot,old.store_snapshot_profile_id)
        correction._validate_totals(new,list(db_session.scalars(select(SettlementStatementLine))),
                                    list(db_session.scalars(select(SettlementStatementEntry))))
    for entry in db_session.scalars(select(SettlementStatementEntry).where(SettlementStatementEntry.source_type == 2)):
        assert entry.adjustment_type_snapshot == 4 and entry.refund_at_snapshot is None and entry.base_amount_cent == 0
    audits = list(db_session.scalars(select(FinanceOperationAudit)))
    assert sum(a.after_snapshot["delta_cent"] == 0 for a in audits) == 4
    assert all(a.operation_type == correction.OPERATION and a.target_type == correction.TARGET_TYPE for a in audits)
    assert all(a.before_snapshot["fee_result"]["fee_result_id"] == a.target_id for a in audits)
    before_replay = fingerprint(db_session)
    assert apply(db_session,manifest,sources,preview)["already_applied"]
    db_session.commit()
    assert fingerprint(db_session) == before_replay


@pytest.mark.parametrize("mutation,reason",[
    (lambda m:m["rows"][0].update(old_fee_cent=1),"FEE_IDENTITY"),
    (lambda m:m["rows"][0].update(store_id="wrong-store"),"FEE_IDENTITY"),
    (lambda m:m["rows"][0].update(expected_entry_id="wrong-entry"),"ENTRY_IDENTITY"),
    (lambda m:m["rows"][0].update(expected_statement_version=99),"STATEMENT_VERSION"),
    (lambda m:m["rows"][0].update(expected_fee_result_id="wrong-fee"),"CURRENT_FEE"),
    (lambda m:m["rows"][0].update(posting_month="2026-10"),"CROSS_MONTH"),
    (lambda m:m["rows"][0].update(business_month="2026-08"),"CROSS_MONTH"),
    (lambda m:m["rows"][0].update(target_fee_cent=1681),"SOURCE_ROW"),
    (lambda m:m["rows"][0].update(source_coupon_code="wrong-code"),"SOURCE_ROW"),
    (lambda m:m["rows"][0].update(source_row_sha256="0"*64),"SOURCE_ROW"),
    (lambda m:m["rows"][0].update(source_sha256="0"*64),"SOURCE_FILE_SHA"),
    (lambda m:m["rows"][0].update(source_row=9999),"SOURCE_ROW_INVALID"),
    (lambda m:m["rows"][0].update(old_fee_cent=True),"INTEGER_CENTS"),
    (lambda m:m["rows"][0].update(target_fee_cent=-1),"INVALID_DIRECTION"),
    (lambda m:m["rows"][0].update(fee_direction=3),"INVALID_DIRECTION"),
    (lambda m:m["rows"].append(deepcopy(m["rows"][0])),"SIXTEEN_DIRECTION"),
    (lambda m:m["rows"].__setitem__(1,deepcopy(m["rows"][0])),"DUPLICATE_COUPON"),
])
def test_invalid_evidence_or_state_rejects_whole_batch(db_session,cohort,mutation,reason):
    manifest,sources = cohort
    before = fingerprint(db_session)
    mutation(manifest)
    with pytest.raises(correction.HistoricalFeeCorrectionError,match=reason):
        correction.apply_correction(db_session,manifest,source_documents=sources,expected_preview_sha256="0"*64)
    assert fingerprint(db_session) == before


def test_stale_preview_detects_outside_source_change(db_session,cohort):
    manifest,sources = cohort
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    outside = db_session.scalar(select(SettlementStatementEntry).where(SettlementStatementEntry.statement_entry_id == "outside-entry"))
    outside.product_name_snapshot = "Changed after preview"
    db_session.commit()
    before = fingerprint(db_session)
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="PREVIEW_STATE_CHANGED"):
        apply(db_session,manifest,sources,preview)
    assert fingerprint(db_session) == before


def protect(session,kind):
    bill = session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "bill-sale-store"))
    if kind in ["status3","status4"]:
        bill.statement_status = int(kind[-1])
    elif kind in ["confirmed_at","locked_at"]:
        setattr(bill,kind,NOW)
    elif kind == "confirmation":
        # Even a confirmation of a historical non-current version protects slot.
        old = correction._copy(bill,statement_id="old-bill",version_no=2,is_current=False)
        session.add(old)
        session.add(SettlementStatementConfirmation(confirmation_id="confirmation",statement_id="old-bill",
            fee_direction=1,confirmation_status=1,confirmed_amount_cent=100,confirmed_by="fake"))
    elif kind == "invoice":
        session.add(InvoiceRecord(invoice_id="invoice",store_id=bill.store_id,statement_month=MONTH,
            statement_id=bill.statement_id,fee_direction=1,invoice_number="00000000000000000001",
            invoice_date=date(2026,10,1),invoice_amount_cent=100,source_type=1,registered_by="fake"))
    elif kind == "allocation":
        session.add(PromotionInvoiceAllocation(allocation_id="allocation",invoice_id="fake-invoice",store_id=bill.store_id,
            statement_id=bill.statement_id,statement_month=MONTH,settlement_batch_month=MONTH,allocated_amount_cent=100,is_current=False))
    elif kind == "dispute":
        session.add(SettlementDispute(dispute_id="dispute",statement_id=bill.statement_id,store_id=bill.store_id,
            statement_month=MONTH,fee_direction=1,dispute_type=1,status=1,description="synthetic",contact_name="fake",
            contact_phone_ciphertext="synthetic",submitted_by="fake"))
    elif kind == "carryforward":
        session.add(SettlementCarryforwardSource(carryforward_source_id="carry",source_event_type=2,
            source_event_key="synthetic",original_fee_result_id="fee-0-1",verify_id="synthetic-verify",
            coupon_id="coupon-0",order_id="order-0",store_id=bill.store_id,fee_direction=1,
            original_business_month=MONTH,event_month=MONTH,adjustment_type=4,adjustment_base_cent=0,
            adjustment_fee_cent=1,rule_version="synthetic",carryforward_reason="synthetic",occurred_at=NOW,created_by="fake"))
    elif kind == "adjustment":
        session.add(SettlementFeeAdjustment(adjustment_id="existing",original_fee_result_id="fee-0-1",
            coupon_id="coupon-0",order_id="order-0",fee_direction=1,original_business_month=MONTH,
            adjustment_posting_month=MONTH,adjustment_type=4,adjustment_fee_cent=1,rule_version="synthetic",
            adjustment_reason="synthetic",occurred_at=NOW,created_by="fake"))
    session.commit()


@pytest.mark.parametrize("kind",["status3","status4","confirmed_at","locked_at","confirmation","invoice","allocation","dispute","carryforward","adjustment"])
def test_all_protection_and_complex_slots_rejected(db_session,cohort,kind):
    manifest,sources = cohort
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    protect(db_session,kind)
    before = fingerprint(db_session)
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="PROTECTED|COMPLEX|EXISTING_ADJUSTMENT"):
        apply(db_session,manifest,sources,preview)
    assert fingerprint(db_session) == before


def test_rollback_after_first_cloned_bill_is_atomic(db_session,cohort,monkeypatch):
    manifest,sources = cohort
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    before = fingerprint(db_session)
    original = correction._clone_bill
    def fail_after_clone(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError("injected midway failure")
    monkeypatch.setattr(correction,"_clone_bill",fail_after_clone)
    with pytest.raises(RuntimeError,match="midway"):
        apply(db_session,manifest,sources,preview)
    db_session.commit()
    assert fingerprint(db_session) == before


def test_same_request_different_payload_and_partial_audit_fail_closed(db_session,cohort):
    manifest,sources = cohort
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    apply(db_session,manifest,sources,preview)
    db_session.commit()
    before = fingerprint(db_session)
    other = deepcopy(manifest)
    other["approval_reference"] += " changed"
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="REQUEST_CONTENT_CONFLICT"):
        apply(db_session,other,sources,preview)
    assert fingerprint(db_session) == before
    audit = db_session.scalar(select(FinanceOperationAudit))
    db_session.delete(audit)
    db_session.commit()
    before = fingerprint(db_session)
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="PARTIAL_OR_DUPLICATE_AUDIT"):
        apply(db_session,manifest,sources,preview)
    assert fingerprint(db_session) == before


def test_replay_never_mutates_new_protected_facts(db_session,cohort):
    manifest,sources = cohort
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    result = apply(db_session,manifest,sources,preview)
    db_session.commit()
    current_id = result["new_statement_ids"]["bill-sale-store"]
    current = db_session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == current_id))
    current.statement_status = 3
    current.confirmed_at = NOW
    db_session.commit()
    before = fingerprint(db_session)
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="PROTECTED"):
        apply(db_session,manifest,sources,preview)
    assert fingerprint(db_session) == before


def test_missing_adjustment_or_tampered_audit_replay_rejected(db_session,cohort):
    manifest,sources = cohort
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    apply(db_session,manifest,sources,preview)
    db_session.commit()
    adjustment = db_session.scalar(select(SettlementFeeAdjustment))
    db_session.delete(adjustment)
    db_session.commit()
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="PARTIAL"):
        apply(db_session,manifest,sources,preview)
    audit = db_session.scalar(select(FinanceOperationAudit))
    audit.after_snapshot = {**audit.after_snapshot,"delta_cent":999}
    db_session.commit()
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="TAMPERED_AUDIT"):
        apply(db_session,manifest,sources,preview)


def test_all_zero_still_audits_every_basis_without_versions_or_adjustments(db_session):
    manifest,sources = seed(db_session,[1680]*8)
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    assert preview["changed_statement_ids"] == []
    result = apply(db_session,manifest,sources,preview)
    db_session.commit()
    assert result["new_statement_ids"] == {} and result["adjustment_ids"] == []
    assert db_session.scalar(select(func.count()).select_from(FinanceOperationAudit)) == 16
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 9
    assert apply(db_session,manifest,sources,preview)["already_applied"]


def test_negative_manual_delta_is_not_a_refund(db_session,cohort):
    manifest,sources = cohort
    document = json.loads(next(iter(sources.values())).decode())
    document["tables"][0][1][3:] = ["10","10"]
    raw = json.dumps(document,ensure_ascii=False).encode()
    sha = hashlib.sha256(raw).hexdigest()
    for row in manifest["rows"]:
        row["source_sha256"] = sha
        if row["coupon_id"] == "coupon-0":
            row["target_fee_cent"] = 1000
            row["source_row_sha256"] = correction.evidence_sha256(document["tables"][0][1])
    apply(db_session,manifest,{sha:raw})
    db_session.commit()
    negatives = list(db_session.scalars(select(SettlementFeeAdjustment).where(SettlementFeeAdjustment.adjustment_fee_cent < 0)))
    assert len(negatives) == 2
    assert all(row.adjustment_fee_cent == -680 and row.adjustment_type == 4 and row.refund_event_id is None for row in negatives)


def test_missing_original_header_or_line_total_rejected(db_session,cohort):
    manifest,sources = cohort
    bill = db_session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "bill-sale-store"))
    bill.promotion_original_fee_cent += 1
    bill.promotion_net_fee_cent += 1
    db_session.commit()
    before = fingerprint(db_session)
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="HEADER_TOTALS_MISMATCH"):
        correction.preview_correction(db_session,manifest,source_documents=sources)
    assert fingerprint(db_session) == before


@pytest.mark.parametrize("kind",["entry-store","current-pointer","not-latest"])
def test_additional_exact_version_and_store_guards(db_session,cohort,kind):
    manifest,sources = cohort
    if kind == "entry-store":
        entry = db_session.scalar(select(SettlementStatementEntry).where(SettlementStatementEntry.statement_entry_id == "entry-fee-0-1"))
        entry.sale_store_id_snapshot = "other-store"
    elif kind == "current-pointer":
        pointer = db_session.scalar(select(SettlementFeeResultCurrent).where(SettlementFeeResultCurrent.fee_result_id == "fee-0-1"))
        pointer.fee_result_id = "unreviewed-result"
    else:
        bill = db_session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "bill-sale-store"))
        db_session.add(correction._copy(bill,statement_id="future-noncurrent",version_no=4,is_current=False))
    db_session.commit()
    before = fingerprint(db_session)
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="ENTRY_RESPONSIBLE|CURRENT_FEE|NOT_LATEST"):
        correction.preview_correction(db_session,manifest,source_documents=sources)
    assert fingerprint(db_session) == before


def test_pending_session_changes_never_autoflush_during_preview(db_session,cohort):
    manifest,sources = cohort
    fee = db_session.scalar(select(SettlementFeeResult).where(SettlementFeeResult.fee_result_id == "fee-0-1"))
    fee.calculation_run_id = "pending-unrelated-write"
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="SESSION_HAS_PENDING_WRITES"):
        correction.preview_correction(db_session,manifest,source_documents=sources)
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(FinanceOperationAudit)) == 0
    assert db_session.scalar(select(SettlementFeeResult.calculation_run_id).where(SettlementFeeResult.fee_result_id == "fee-0-1")) == "synthetic-run"


def test_null_audit_snapshot_is_explicit_integrity_failure(db_session,cohort):
    manifest,sources = cohort
    preview = correction.preview_correction(db_session,manifest,source_documents=sources)
    apply(db_session,manifest,sources,preview)
    db_session.commit()
    for audit in db_session.scalars(select(FinanceOperationAudit)):
        audit.after_snapshot = None
    db_session.commit()
    before = fingerprint(db_session)
    with pytest.raises(correction.HistoricalFeeCorrectionError,match="INCOMPLETE_OR_TAMPERED_AUDIT"):
        apply(db_session,manifest,sources,preview)
    assert fingerprint(db_session) == before
