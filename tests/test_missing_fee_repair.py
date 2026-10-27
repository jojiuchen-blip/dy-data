"""Exact first-fee repair eligibility and side-effect-free shared quotations."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timezone
import json

import pytest
from sqlalchemy import event, func, select

from apps.api.dy_api import models as m
from apps.worker import missing_fee_repair as repair
from apps.worker import settlement as s
from test_receipt_commission_basis import _add_dual_order, _seed_dual_base


def setup_batch(session, *, count=1):
    _seed_dual_base(session)
    entries = []
    for index in range(count):
        coupon_id = f"repair-coupon-{index}"
        order_id = f"repair-order-{index}"
        _add_dual_order(session, order_id, paid_cent=11000,
                        coupons=[{"coupon_id": coupon_id, "receipt_amount": 10000}])
        coupon = session.scalar(select(m.RawDouyinOrderCoupon).where(m.RawDouyinOrderCoupon.coupon_id == coupon_id))
        verify = session.get(m.RawDouyinVerifyRecord, f"verify-{coupon_id}")
        entries.append({"coupon_id": coupon_id, "order_id": order_id,
                        "raw_coupon_id": coupon.id, "raw_order_id": coupon.raw_order_id,
                        "business_month": "2026-09", "expected_sale_store_id": "store-sale",
                        "expected_verify_store_id": "store-verify", "verify_id": verify.verify_id,
                        "verify_time": repair.canonical(verify.verify_time)})
    session.commit()
    manifest = {"schema_version": 1, "request_id": "synthetic-reviewed-repair",
                "approval_ref": "DYDATA-104/synthetic-test-only", "actor": "ops:synthetic-test",
                "coupons": entries}
    exclusions = {"schema_version": 1, "groups": {
        name: {"coupon_ids": [], "count": 0, "sha256": repair.digest([])}
        for name in sorted(repair.EXCLUSION_GROUPS)}}
    return manifest, exclusions


def preview(session, manifest, exclusions):
    return repair.preview_missing_fees(session, manifest=manifest, exclusions=exclusions)


def test_preview_emits_select_only_and_quote_is_frozen(db_session):
    manifest, exclusions = setup_batch(db_session, count=2)
    statements = []
    def record(_conn, _cursor, statement, *_):
        statements.append(statement.upper())
    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        report = preview(db_session, manifest, exclusions)
        coupon = db_session.get(m.RawDouyinOrderCoupon, manifest["coupons"][0]["raw_coupon_id"])
        order = db_session.get(m.RawDouyinOrder, coupon.raw_order_id)
        quote = repair.quote_new_fee(db_session, coupon=coupon, order=order, direction=1)
        with pytest.raises(FrozenInstanceError):
            quote.fee_amount_cent = 0
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)
    assert all(sql.lstrip().startswith("SELECT") for sql in statements)
    assert not any("FOR UPDATE" in sql or "ADVISORY" in sql or "LOCK TABLE" in sql for sql in statements)
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert len(report["quotes"]) == 4
    assert [row["fee_amount_cent"] for row in report["quotes"]] == [1000, 2000, 1000, 2000]


@pytest.mark.parametrize("mutation", ["missing-group", "group-count", "group-hash", "excluded", "duplicate",
                                      "cross-month", "wrong-order", "wrong-store", "wrong-verify", "wrong-raw",
                                      "too-many", "empty"])
def test_manifest_and_exclusion_tamper_fail_closed(db_session, mutation):
    manifest, exclusions = setup_batch(db_session)
    entry = manifest["coupons"][0]
    if mutation == "missing-group":
        del exclusions["groups"]["paused22"]
    elif mutation.startswith("group-"):
        exclusions["groups"]["paused22"]["count" if mutation == "group-count" else "sha256"] = 1
    elif mutation == "excluded":
        values = [entry["coupon_id"]]
        exclusions["groups"]["paused22"] = {"coupon_ids": values, "count": 1, "sha256": repair.digest(values)}
    elif mutation == "duplicate":
        manifest["coupons"].append(deepcopy(entry))
    elif mutation == "cross-month":
        entry["business_month"] = "2026-08"
    elif mutation == "wrong-order":
        entry["order_id"] = "unapproved-order"
    elif mutation == "wrong-store":
        entry["expected_sale_store_id"] = "store-verify"
    elif mutation == "wrong-verify":
        entry["verify_id"] = "unapproved-verify"
    elif mutation == "wrong-raw":
        entry["raw_coupon_id"] += 200
    elif mutation == "too-many":
        manifest["coupons"] *= 501
    elif mutation == "empty":
        manifest["coupons"] = []
    with pytest.raises(repair.MissingFeeRepairError):
        preview(db_session, manifest, exclusions)
    assert not db_session.new and not db_session.dirty
    assert db_session.scalar(select(func.count()).select_from(m.SettlementFeeResult)) == 0
    assert db_session.scalar(select(func.count()).select_from(m.FinanceOperationAudit)) == 0


@pytest.mark.parametrize("mutation", ["sku", "owner", "channel", "sale-time", "preformal-sale", "verify",
                                      "poi", "scope", "fee-rule", "receipt", "october", "preformal-verify"])
def test_quote_rejection_never_writes_or_locks(db_session, mutation):
    manifest, _ = setup_batch(db_session)
    coupon = db_session.get(m.RawDouyinOrderCoupon, manifest["coupons"][0]["raw_coupon_id"])
    order = db_session.get(m.RawDouyinOrder, coupon.raw_order_id)
    verify = db_session.get(m.RawDouyinVerifyRecord, manifest["coupons"][0]["verify_id"])
    if mutation == "sku":
        order.sku_id = "missing"
    elif mutation == "owner":
        db_session.scalar(select(m.DimSkuProductRule)).owner_account_id = None
    elif mutation == "channel":
        order.sale_channel_normalized = "unknown"
    elif mutation == "sale-time":
        order.sale_time = order.pay_time = None
    elif mutation == "preformal-sale":
        order.sale_time = order.pay_time = datetime(2026, 7, 1, tzinfo=timezone.utc)
    elif mutation == "verify":
        db_session.delete(verify)
    elif mutation == "poi":
        verify.poi_id = "missing"
    elif mutation == "scope":
        db_session.scalar(select(m.SettlementScopeRule)).is_active = False
    elif mutation == "fee-rule":
        db_session.delete(db_session.scalar(select(m.SkuFeeRule)))
    elif mutation == "receipt":
        coupon.raw_payload = {}
    elif mutation == "october":
        verify.verify_time = datetime(2026, 10, 5, tzinfo=timezone.utc)
    elif mutation == "preformal-verify":
        verify.verify_time = datetime(2026, 7, 5, tzinfo=timezone.utc)
    db_session.commit()
    statements = []
    def record(_conn, _cursor, statement, *_):
        statements.append(statement.upper())
    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        with pytest.raises(repair.NewFeeQuoteError):
            repair.quote_new_fee(db_session, coupon=coupon, order=order, direction=1)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)
    assert all(sql.lstrip().startswith("SELECT") for sql in statements)
    assert not any("FOR UPDATE" in sql or "ADVISORY" in sql for sql in statements)
    assert not db_session.new and not db_session.dirty and not db_session.deleted
    assert db_session.scalar(select(func.count()).select_from(m.DataQualityIssue)) == 0


def test_default_writer_matches_every_quote_field(db_session):
    manifest, exclusions = setup_batch(db_session)
    report = preview(db_session, manifest, exclusions)
    stats = s.rebuild_dual_fee_results(db_session, calculation_run_id="ordinary-existing-writer",
                                      coupon_ids=[manifest["coupons"][0]["coupon_id"]])
    assert (stats.result_count, stats.adjustment_count, stats.blocked_count) == (2, 0, 0)
    actual = repair._actual_outputs(db_session, [manifest["coupons"][0]["coupon_id"]],
                                    calculation_run_id="ordinary-existing-writer")
    assert actual == report["quotes"]
    db_session.commit()
    with pytest.raises(repair.MissingFeeRepairError, match="history"):
        preview(db_session, manifest, exclusions)


def test_preview_requires_fresh_session_and_apply_rejects_sqlite(db_session):
    manifest, exclusions = setup_batch(db_session)
    db_session.scalar(select(m.RawDouyinOrder))
    with pytest.raises(repair.MissingFeeRepairError, match="fresh"):
        preview(db_session, manifest, exclusions)
    db_session.rollback()
    with pytest.raises(repair.MissingFeeRepairError, match="PostgreSQL"):
        repair.apply_missing_fees(db_session, manifest=manifest, exclusions=exclusions, preview_hash="a" * 64)


@pytest.mark.parametrize("mutation", ["refund-amount", "refund-date", "closed", "cancel", "multiple-verify", "raw-refund"])
def test_refund_cancel_and_multiverify_reject_whole_batch(db_session, mutation):
    manifest, exclusions = setup_batch(db_session, count=2)
    entry = manifest["coupons"][1]
    coupon = db_session.get(m.RawDouyinOrderCoupon, entry["raw_coupon_id"])
    verify = db_session.get(m.RawDouyinVerifyRecord, entry["verify_id"])
    if mutation == "refund-amount":
        coupon.coupon_refunded_amount_cent = 1
    elif mutation == "refund-date":
        coupon.latest_refund_at = datetime.now(timezone.utc)
    elif mutation == "closed":
        db_session.get(m.RawDouyinOrder, entry["raw_order_id"]).order_status_normalized = "closed"
    elif mutation == "cancel":
        verify.cancel_time = datetime.now(timezone.utc)
    elif mutation == "multiple-verify":
        db_session.add(m.RawDouyinVerifyRecord(verify_id="another-verify", coupon_id=coupon.coupon_id,
                       verify_status="valid", verify_time=verify.verify_time, poi_id=verify.poi_id))
    elif mutation == "raw-refund":
        db_session.add(m.RawDouyinRefundRecord(source_record_key="synthetic-refund", order_id=entry["order_id"],
                                              payload_hash="a" * 64))
    db_session.commit()
    with pytest.raises(repair.MissingFeeRepairError):
        preview(db_session, manifest, exclusions)
    assert db_session.scalar(select(func.count()).select_from(m.SettlementFeeResult)) == 0


@pytest.mark.parametrize("history", ["pointer", "adjustment", "carryforward", "entry", "stale-bill", "multiple-current"])
def test_orphan_financial_history_rejects_even_without_fee_results(db_session, history):
    manifest, exclusions = setup_batch(db_session)
    entry = manifest["coupons"][0]
    if history == "pointer":
        db_session.add(m.SettlementFeeResultCurrent(coupon_id=entry["coupon_id"], fee_direction=1,
                                                   fee_result_id="orphan-result"))
    elif history == "adjustment":
        db_session.add(m.SettlementFeeAdjustment(adjustment_id="orphan-adjustment", original_fee_result_id="absent",
            coupon_id=entry["coupon_id"], order_id=entry["order_id"], fee_direction=1, original_business_month="2026-08",
            adjustment_posting_month="2026-09", adjustment_type=1, rule_version="synthetic", adjustment_reason="test",
            occurred_at=datetime.now(timezone.utc), created_by="synthetic-test"))
    elif history == "carryforward":
        db_session.add(m.SettlementCarryforwardSource(carryforward_source_id="orphan-source", source_event_key="verify:orphan",
            source_event_type=2, original_fee_result_id="absent", verify_id="absent", coupon_id=entry["coupon_id"],
            order_id=entry["order_id"], store_id="store-sale", fee_direction=1, original_business_month="2026-08",
            event_month="2026-09", adjustment_type=1, rule_version="synthetic", carryforward_reason="test",
            occurred_at=datetime.now(timezone.utc), created_by="synthetic-test"))
    elif history == "entry":
        db_session.add(m.SettlementStatementEntry(statement_entry_id="orphan-entry", statement_id="absent",
            statement_line_id="absent", source_type=1, source_record_id="absent", original_fee_result_id="absent",
            coupon_id=entry["coupon_id"], order_id=entry["order_id"], fee_direction=1,
            original_business_month="2026-08", statement_posting_month="2026-09", rule_version="synthetic"))
    elif history in {"stale-bill", "multiple-current"}:
        if history == "multiple-current":
            from sqlalchemy import text
            db_session.execute(text("DROP INDEX idx_settlement_statement_current_slot"))
        db_session.add(m.SettlementStatement(statement_id="stale-bill", store_id="store-sale", statement_month="2026-09",
                                             is_current=history == "multiple-current"))
        if history == "multiple-current":
            db_session.add(m.SettlementStatement(statement_id="another-current", store_id="store-sale", statement_month="2026-09",
                                                 version_no=2, is_current=True))
    db_session.commit()
    with pytest.raises(repair.MissingFeeRepairError, match="history"):
        preview(db_session, manifest, exclusions)
    assert db_session.scalar(select(func.count()).select_from(m.SettlementFeeResult)) == 0


def test_full_manifest_exclusions_and_budget_bound_into_hash(db_session):
    manifest, exclusions = setup_batch(db_session)
    baseline = preview(db_session, manifest, exclusions)
    manifest["approval_attachment_sha256"] = "a" * 64
    assert preview(db_session, manifest, exclusions)["preview_hash"] != baseline["preview_hash"]
    baseline = preview(db_session, manifest, exclusions)
    exclusions["source_evidence"] = {"reviewed": "synthetic-only"}
    assert preview(db_session, manifest, exclusions)["preview_hash"] != baseline["preview_hash"]
    assert baseline["budget"] == repair.BUDGET


def test_cli_defaults_to_preview_and_private_report(db_session, tmp_path, monkeypatch, capsys):
    from scripts.ops import repair_missing_fees as cli
    manifest, exclusions = setup_batch(db_session)
    manifest_path, exclusions_path = tmp_path / "manifest.json", tmp_path / "exclusions.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    exclusions_path.write_text(json.dumps(exclusions), encoding="utf-8")
    output = tmp_path / "private-preview.json"
    engine = db_session.get_bind()
    monkeypatch.setattr(cli, "make_engine", lambda: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    assert cli.main(["--manifest", str(manifest_path), "--exclusions", str(exclusions_path),
                     "--output", str(output)]) == 0
    visible = capsys.readouterr()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert not report["applied"] and len(report["quotes"]) == 2
    assert manifest["coupons"][0]["coupon_id"] not in visible.out
    assert visible.err == ""
    assert db_session.scalar(select(func.count()).select_from(m.SettlementFeeResult)) == 0


def test_cli_existing_report_rejected_before_database_open(tmp_path, monkeypatch):
    from scripts.ops import repair_missing_fees as cli
    manifest_path, exclusions_path, output = (tmp_path / name for name in ("manifest.json", "exclusions.json", "existing.json"))
    manifest_path.write_text('{"request_id":"synthetic"}', encoding="utf-8")
    exclusions_path.write_text('{}', encoding="utf-8")
    output.write_text("preserve existing evidence", encoding="utf-8")
    def forbidden():
        raise AssertionError("database must not open for an existing report")
    monkeypatch.setattr(cli, "make_engine", forbidden)
    assert cli.main(["--manifest", str(manifest_path), "--exclusions", str(exclusions_path),
                     "--output", str(output)]) == 2
    assert output.read_text(encoding="utf-8") == "preserve existing evidence"


def test_cli_rejects_tracked_report_path():
    from scripts.ops import repair_missing_fees as cli
    with pytest.raises(repair.MissingFeeRepairError, match="private report"):
        cli._private_destination(cli.ROOT / "apps" / "worker" / "settlement.py")
