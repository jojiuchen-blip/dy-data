"""Exact historical decisions must never become current account bindings."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    DataQualityIssue, DimAwemeAccount, DimStore, DouyinRefundEvent,
    HistoricalSaleAttributionDecision, JobEvent, JobRun, PromotionInvoiceAllocation,
    RawAwemeBinding, RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord,
    SettlementFeeAdjustment, SettlementFeeResult, SettlementScopeRule, SettlementStatement, SkuFeeRule,
)
from apps.worker import historical_sale_attribution as history, month_close, settlement
from test_data_settlement import _load_dual_fee_fixture, _fee_result, _dual_time


def _iso(value):
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


def reviewed_manifest(session, *, ambiguous_binding=True):
    _load_dual_fee_fixture(session, amount_cent=10000)
    order = session.scalar(select(RawDouyinOrder))
    order.owner_account_id = "_000-synthetic-source-account"
    order.owner_account_name = "Historical synthetic seller"
    if ambiguous_binding:
        for status in ("active", "unbound"):
            session.add(RawAwemeBinding(
                binding_key=f"historical-binding-{status}", account_id="store-sale",
                douyin_nickname=order.owner_account_name, binding_status=status,
                douyin_id="synthetic-uid", poi_id="synthetic-sale-poi", raw_payload={},
            ))
    session.flush()
    coupon = session.scalar(select(RawDouyinOrderCoupon))
    verify = session.scalar(select(RawDouyinVerifyRecord))
    return {
        "batch_id": "synthetic-reviewed-batch", "actor": "synthetic-operator",
        "evidence_sha256": "a" * 64,
        "approval_evidence": {"issue": "DYDATA-104", "approval": "synthetic user review"},
        "rows": [{
            "raw_order_id": order.id, "order_id": order.order_id,
            "raw_coupon_id": coupon.id, "coupon_id": coupon.coupon_id,
            "source_account_id": order.owner_account_id, "store_id": "store-sale",
            "verify_id": verify.verify_id, "verify_time": _iso(verify.verify_time),
            "business_month": "2026-09", "approved_business_months": ["2026-09"],
            "sale_time": _iso(order.sale_time), "pay_time": _iso(order.pay_time),
            "order_payload_fingerprint": order.payload_fingerprint,
            "coupon_payload_fingerprint": coupon.payload_fingerprint,
            "verify_payload_fingerprint": verify.payload_fingerprint,
        }],
    }


def test_import_defaults_to_dry_run_and_apply_replays_after_durable_readback(db_session):
    manifest = reviewed_manifest(db_session)
    first = history.import_decisions(db_session, manifest)
    assert first["mode"] == "dry-run" and first["new_count"] == 1
    assert list(db_session.scalars(select(HistoricalSaleAttributionDecision))) == []
    assert list(db_session.scalars(select(JobRun))) == []
    applied = history.import_decisions(db_session, manifest, apply=True)
    db_session.commit()
    db_session.expire_all()
    rows = list(db_session.scalars(select(HistoricalSaleAttributionDecision)))
    assert len(rows) == 1 and rows[0].source_account_id == "_000-synthetic-source-account"
    assert rows[0].approval_evidence_json == manifest["approval_evidence"]
    assert rows[0].store_id == "store-sale"
    assert applied["new_count"] == 1
    assert history.import_decisions(db_session, manifest, apply=True)["existing_count"] == 1
    assert len(list(db_session.scalars(select(JobRun)))) == 1
    assert len(list(db_session.scalars(select(JobEvent)))) == 1
    assert all(row.job_name != "settlement_rebuild" for row in db_session.scalars(select(JobRun)))


def test_exact_decision_enables_dual_fees_without_changing_raw_or_dim_bindings(db_session):
    manifest = reviewed_manifest(db_session)
    order = db_session.scalar(select(RawDouyinOrder))
    assert settlement._resolve_dual_fee_sale_account(db_session, order) is None
    original_bindings = [(r.binding_key, r.binding_status) for r in db_session.scalars(select(RawAwemeBinding))]
    original_accounts = [(r.account_id, r.store_id, r.binding_status, r.valid_from, r.valid_to)
                         for r in db_session.scalars(select(DimAwemeAccount))]
    history.import_decisions(db_session, manifest, apply=True)
    db_session.commit()
    source_dml = []
    def watch(conn, cursor, statement, parameters, context, executemany):
        normalized = statement.strip().lower()
        if normalized.startswith(("insert ", "update ", "delete ")) and any(
            name in normalized for name in ("raw_aweme_bindings", "dim_aweme_accounts", "user_", "account_permission")
        ):
            source_dml.append(statement)
    event.listen(db_session.get_bind(), "before_cursor_execute", watch)
    try:
        settlement.rebuild_dual_fee_results(db_session, calculation_run_id="historical-calc")
        db_session.commit()
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", watch)
    for direction, fee in ((1, 3000), (2, 2000)):
        result = _fee_result(db_session, "coupon-dual", direction)
        assert result is not None
        assert result.sale_store_id == "store-sale" and result.fee_amount_cent == fee
        decision = db_session.get(HistoricalSaleAttributionDecision, result.sale_attribution_decision_id)
        assert decision is not None and decision.batch_id == manifest["batch_id"]
    assert source_dml == []
    assert original_bindings == [(r.binding_key, r.binding_status) for r in db_session.scalars(select(RawAwemeBinding))]
    assert original_accounts == [(r.account_id, r.store_id, r.binding_status, r.valid_from, r.valid_to)
                                for r in db_session.scalars(select(DimAwemeAccount))]
    assert settlement._resolve_dual_fee_sale_account(db_session, order) is None


@pytest.mark.parametrize("field,value", [
    ("source_account_id", "different-namespace"), ("raw_order_id", 999),
    ("raw_coupon_id", 999), ("order_id", "another-order"),
    ("verify_id", "another-verification"), ("business_month", "2026-08"),
    ("verify_time", "2026-09-05T03:00:00+00:00"),
    ("store_id", "missing-store"), ("order_payload_fingerprint", "b" * 64),
])
def test_manifest_identity_drift_rejects_entire_batch(db_session, field, value):
    manifest = reviewed_manifest(db_session)
    manifest["rows"][0][field] = value
    with pytest.raises(history.HistoricalAttributionError):
        history.import_decisions(db_session, manifest, apply=True)
    assert list(db_session.scalars(select(HistoricalSaleAttributionDecision))) == []
    assert list(db_session.scalars(select(JobRun))) == []


@pytest.mark.parametrize("mutation", ["owner", "verify_time", "verify_id", "coupon_link"])
def test_later_source_drift_blocks_instead_of_falling_back(db_session, mutation):
    manifest = reviewed_manifest(db_session)
    history.import_decisions(db_session, manifest, apply=True)
    order = db_session.scalar(select(RawDouyinOrder))
    coupon = db_session.scalar(select(RawDouyinOrderCoupon))
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    if mutation == "owner":
        order.owner_account_id = "changed-source-account"
    elif mutation == "verify_time":
        verify.verify_time += timedelta(days=31)
    elif mutation == "verify_id":
        verify.verify_status = "cancelled"
    elif mutation == "coupon_link":
        coupon.order_id = "wrong-business-order"
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="changed-input")
    assert list(db_session.scalars(select(SettlementFeeResult))) == []


@pytest.mark.parametrize("change", ["refund", "cancel"])
def test_approved_fee_keeps_normal_refund_and_cancellation_adjustments(db_session, change):
    manifest = reviewed_manifest(db_session)
    history.import_decisions(db_session, manifest, apply=True)
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="approved-original")
    originals = list(db_session.scalars(select(SettlementFeeResult)))
    frozen = [(r.fee_result_id, r.fee_amount_cent, r.input_fingerprint, r.qualifying_verify_id,
               r.qualifying_verify_time, r.sale_attribution_decision_id) for r in originals]
    decision = db_session.scalar(select(HistoricalSaleAttributionDecision))
    original_identity, original_digest = deepcopy(decision.source_identity_json), decision.source_identity_sha256
    order = db_session.scalar(select(RawDouyinOrder))
    coupon = db_session.scalar(select(RawDouyinOrderCoupon))
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    order.payload_fingerprint, coupon.payload_fingerprint, verify.payload_fingerprint = "b" * 64, "c" * 64, "d" * 64
    if change == "refund":
        coupon.coupon_refunded_amount_cent = 4000
        db_session.add(DouyinRefundEvent(
            refund_event_id="reviewed-refund", order_id=order.order_id, coupon_id=coupon.coupon_id,
            refund_type=1, refund_status=2, refund_amount_cent=4000,
            occurred_at=_dual_time(10, 8), successful_observed_at=originals[0].calculated_at + timedelta(seconds=1),
            source_run_id="synthetic-refund", raw_payload={},
        ))
    else:
        verify.verify_status = "cancelled"
        verify.cancel_time = _dual_time(10, 8)
    db_session.flush()
    for run_id in ("approved-financial-event", "approved-financial-event-repeat"):
        settlement.rebuild_dual_fee_results(db_session, calculation_run_id=run_id)
    rows = list(db_session.scalars(select(SettlementFeeResult)))
    assert [(r.fee_result_id, r.fee_amount_cent, r.input_fingerprint, r.qualifying_verify_id,
             r.qualifying_verify_time, r.sale_attribution_decision_id) for r in rows] == frozen
    assert (decision.source_identity_json, decision.source_identity_sha256) == (original_identity, original_digest)
    adjustments = list(db_session.scalars(select(SettlementFeeAdjustment)))
    assert len(adjustments) == 2
    assert {row.adjustment_posting_month for row in adjustments} == {"2026-10"}
    expected = {1: -1200, 2: -800} if change == "refund" else {1: -3000, 2: -2000}
    assert {row.fee_direction: row.adjustment_fee_cent for row in adjustments} == expected
    assert list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "historical_sale_attribution_source_drift",
    ))) == []
    # Mutable financial observations do not relax the import approval check.
    with pytest.raises(history.HistoricalAttributionError, match="identity"):
        history.import_decisions(db_session, manifest, apply=True)


def test_cancelled_decision_without_a_frozen_fee_cannot_create_new_fees(db_session):
    manifest = reviewed_manifest(db_session)
    history.import_decisions(db_session, manifest, apply=True)
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    verify.verify_status, verify.cancel_time = "cancelled", _dual_time(10, 8)
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="cancel-before-first-fee")
    assert list(db_session.scalars(select(SettlementFeeResult))) == []
    assert list(db_session.scalars(select(SettlementFeeAdjustment))) == []


@pytest.mark.parametrize("reuse_verify_id", [False, True])
def test_reverification_does_not_expand_exact_approval(db_session, reuse_verify_id):
    manifest = reviewed_manifest(db_session)
    history.import_decisions(db_session, manifest, apply=True)
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="before-new-verification")
    original_ids = {r.fee_result_id for r in db_session.scalars(select(SettlementFeeResult))}
    verify = db_session.scalar(select(RawDouyinVerifyRecord))
    if reuse_verify_id:
        verify.verify_time = _dual_time(10, 9)
    else:
        verify.verify_status, verify.cancel_time = "cancelled", _dual_time(10, 8)
        db_session.add(RawDouyinVerifyRecord(
            verify_id="new-unapproved-verification", coupon_id=verify.coupon_id,
            verify_status="valid", verify_time=_dual_time(10, 9), poi_id=verify.poi_id,
            sku_id=verify.sku_id, paid_amount_cent=10000, raw_payload={},
        ))
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="unapproved-reverification")
    assert {r.fee_result_id for r in db_session.scalars(select(SettlementFeeResult))} == original_ids
    assert list(db_session.scalars(select(SettlementFeeAdjustment).where(SettlementFeeAdjustment.adjustment_type == 4))) == []
    assert list(db_session.scalars(select(DataQualityIssue).where(
        DataQualityIssue.issue_type == "historical_sale_attribution_source_drift",
    )))


def test_inconsistent_redundant_decision_identity_fails_closed(db_session):
    manifest = reviewed_manifest(db_session)
    history.import_decisions(db_session, manifest, apply=True)
    # Metadata-only fixtures omit DDL triggers; simulate corruption to exercise
    # the independent resolver check. Real migrated storage refuses this DML.
    decision = db_session.scalar(select(HistoricalSaleAttributionDecision))
    decision.source_account_id = "inconsistent-ledger-column"
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="corrupt-evidence")
    assert list(db_session.scalars(select(SettlementFeeResult))) == []


def test_duplicate_scope_and_conflicting_reimport_never_replace_decision(db_session):
    manifest = reviewed_manifest(db_session)
    duplicate = deepcopy(manifest)
    duplicate["rows"].append(deepcopy(duplicate["rows"][0]))
    with pytest.raises(history.HistoricalAttributionError, match="duplicate"):
        history.import_decisions(db_session, duplicate, apply=True)
    history.import_decisions(db_session, manifest, apply=True)
    db_session.commit()
    conflicting = deepcopy(manifest)
    conflicting["evidence_sha256"] = "d" * 64
    with pytest.raises(history.HistoricalAttributionError):
        history.import_decisions(db_session, conflicting, apply=True)
    assert len(list(db_session.scalars(select(HistoricalSaleAttributionDecision)))) == 1


def test_second_invalid_row_rejects_first_valid_row_without_partial_audit(db_session):
    manifest = reviewed_manifest(db_session)
    second = deepcopy(manifest["rows"][0])
    second.update(coupon_id="zz-invalid-coupon", raw_coupon_id=999)
    manifest["rows"].append(second)
    with pytest.raises(history.HistoricalAttributionError):
        history.import_decisions(db_session, manifest, apply=True)
    assert list(db_session.scalars(select(HistoricalSaleAttributionDecision))) == []
    assert list(db_session.scalars(select(JobEvent))) == []
    assert list(db_session.scalars(select(JobRun))) == []


@pytest.mark.parametrize("state", ["running", "retry_wait"])
def test_import_rejects_live_source_writer(db_session, state):
    manifest = reviewed_manifest(db_session)
    db_session.add(JobRun(job_id="synthetic-running", job_name="settlement_rebuild", status=state))
    db_session.flush()
    with pytest.raises(history.HistoricalAttributionError, match="writer"):
        history.import_decisions(db_session, manifest, apply=True)
    assert list(db_session.scalars(select(HistoricalSaleAttributionDecision))) == []


@pytest.mark.parametrize("gate", ["no_rule", "future_rule", "scope", "unpaid", "receipt", "inactive_store"])
def test_exact_decision_keeps_remaining_qualification_gates(db_session, gate):
    manifest = reviewed_manifest(db_session)
    history.import_decisions(db_session, manifest, apply=True)
    if gate == "no_rule":
        for rule in db_session.scalars(select(SkuFeeRule)):
            db_session.delete(rule)
    elif gate == "future_rule":
        for offset, rule in enumerate(db_session.scalars(select(SkuFeeRule))):
            rule.effective_date = _dual_time(10, 1 + offset).date()
    elif gate == "scope":
        for rule in db_session.scalars(select(SettlementScopeRule)):
            rule.is_active = False
    elif gate == "unpaid":
        order = db_session.scalar(select(RawDouyinOrder))
        order.order_status_normalized = "unpaid"
        order.order_status = "unpaid"
    elif gate == "receipt":
        coupon = db_session.scalar(select(RawDouyinOrderCoupon))
        coupon.raw_payload = {}
        db_session.scalar(select(RawDouyinOrder)).raw_payload = {}
    else:
        db_session.get(DimStore, "store-sale").is_active = False
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="still-gated-" + gate)
    assert list(db_session.scalars(select(SettlementFeeResult))) == []


def test_decision_does_not_apply_to_another_coupon_or_bypass_downstream_fee_rule(db_session):
    manifest = reviewed_manifest(db_session)
    history.import_decisions(db_session, manifest, apply=True)
    db_session.scalar(select(RawDouyinOrder)).sale_channel_normalized = "other"
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="still-invalid-channel")
    assert list(db_session.scalars(select(SettlementFeeResult))) == []
    coupon = db_session.scalar(select(RawDouyinOrderCoupon))
    fake = RawDouyinOrderCoupon(coupon_id="not-approved", order_id=coupon.order_id, raw_order_id=coupon.raw_order_id)
    assert history.resolve_historical_sale_attribution(db_session, order=db_session.scalar(select(RawDouyinOrder)), coupon=fake, verify=None) is None


def test_watermark_changes_only_in_the_decision_month(db_session, monkeypatch):
    manifest = reviewed_manifest(db_session)
    monkeypatch.setattr(month_close, "published_days_revisions", lambda *_: ["synthetic-finalize"])
    monkeypatch.setattr(month_close, "month_current_results_fingerprint", lambda *_: ("unchanged-result", 2))
    before = {month: month_close.month_source_watermark(db_session, month) for month in ("2026-08", "2026-09")}
    history.import_decisions(db_session, manifest, apply=True)
    after = {month: month_close.month_source_watermark(db_session, month) for month in before}
    assert before["2026-08"] == after["2026-08"]
    assert before["2026-09"] != after["2026-09"]


def test_empty_ledger_preserves_existing_watermark_and_incomplete_gates(db_session, monkeypatch):
    monkeypatch.setattr(month_close, "published_days_revisions", lambda *_: ["original-finalize"])
    monkeypatch.setattr(month_close, "month_current_results_fingerprint", lambda *_: ("original-result", 2))
    expected = hashlib.sha256(b"original-finalize||original-result").hexdigest()[:12]
    assert month_close.month_source_watermark(db_session, "2026-09") == expected
    reviewed = reviewed_manifest(db_session)
    history.import_decisions(db_session, reviewed, apply=True)
    monkeypatch.setattr(month_close, "published_days_revisions", lambda *_: None)
    assert month_close.month_source_watermark(db_session, "2026-09") is None
    monkeypatch.setattr(month_close, "published_days_revisions", lambda *_: ["original-finalize"])
    monkeypatch.setattr(month_close, "month_current_results_fingerprint", lambda *_: ("no-result", 0))
    assert month_close.month_source_watermark(db_session, "2026-09") is None


def test_cli_dry_run_and_apply_hash_gate(db_session, monkeypatch, tmp_path, capsys):
    manifest = reviewed_manifest(db_session)
    db_session.commit()
    path = tmp_path / "synthetic-manifest.json"
    raw = json.dumps(manifest).encode()
    path.write_bytes(raw)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)
    monkeypatch.setattr("apps.api.dy_api.db.get_session_factory", lambda: factory)
    monkeypatch.setattr(sys, "argv", ["history", "--manifest", str(path)])
    history.main()
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"
    assert list(db_session.scalars(select(HistoricalSaleAttributionDecision))) == []
    monkeypatch.setattr(sys, "argv", ["history", "--manifest", str(path), "--apply", "--expected-sha256", "0" * 64])
    with pytest.raises(SystemExit):
        history.main()
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["history", "--manifest", str(path), "--apply", "--expected-sha256", hashlib.sha256(raw).hexdigest()])
    history.main()
    report = json.loads(capsys.readouterr().out)
    assert report["readback_count"] == 1 and report["readback_verified"] is True


@pytest.mark.parametrize("protected", ["confirmed", "locked", "invoice"])
def test_exact_decision_never_overwrites_protected_statement_or_amount(db_session, protected):
    manifest = reviewed_manifest(db_session, ambiguous_binding=False)
    order = db_session.scalar(select(RawDouyinOrder))
    # Start with valid ordinary evidence, then preserve its financial fact.
    order.owner_account_id = "owner-dual"
    db_session.flush()
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="original-valid-result")
    original = _fee_result(db_session, "coupon-dual", 1)
    original_id, original_amount = original.fee_result_id, original.fee_amount_cent
    order.owner_account_id = manifest["rows"][0]["source_account_id"]
    if protected == "invoice":
        db_session.add(PromotionInvoiceAllocation(
            allocation_id="protected-allocation", invoice_id="synthetic-existing-invoice",
            store_id="store-sale", statement_id="synthetic-invoiced-statement",
            statement_month="2026-09", settlement_batch_month="2026-09",
            allocated_amount_cent=original_amount, is_current=True,
        ))
    else:
        db_session.add(SettlementStatement(statement_id="protected-history", store_id="store-sale",
            statement_month="2026-09", statement_status=3 if protected == "confirmed" else 4,
            confirmed_at=_dual_time(10, 1) if protected == "confirmed" else None,
            locked_at=_dual_time(10, 1) if protected == "locked" else None))
    db_session.flush()
    history.import_decisions(db_session, manifest, apply=True)
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="historical-protected", force_recalculate=True)
    current = _fee_result(db_session, "coupon-dual", 1)
    assert (current.fee_result_id, current.fee_amount_cent) == (original_id, original_amount)
    assert current.sale_attribution_decision_id is None
    if protected == "invoice":
        allocation = db_session.scalar(select(PromotionInvoiceAllocation))
        assert allocation.allocated_amount_cent == original_amount and allocation.is_current is True


def test_sqlite_migration_retains_fee_tracking_and_enforces_immutable_ledger(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    url = "sqlite+pysqlite:///" + (tmp_path / "synthetic-history.sqlite").as_posix()
    config.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url)
    try:
        command.upgrade(config, "20261022_0064")
        with engine.connect() as connection:
            before = connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='settlement_fee_result' ORDER BY name")).all()
        command.upgrade(config, "head")
        with engine.connect() as connection:
            after = connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='settlement_fee_result' ORDER BY name")).all()
        assert before == after and len(after) == 3
        with Session(engine, autoflush=False) as session:
            history.import_decisions(session, reviewed_manifest(session), apply=True)
            session.commit()
            assert session.scalar(text("SELECT generation FROM dashboard_publication_source_counters WHERE source_name=:source"), {"source": history.TABLE_NAME}) == 1
            for sql in ("UPDATE historical_sale_attribution_decisions SET actor='changed'", "DELETE FROM historical_sale_attribution_decisions"):
                with pytest.raises(DBAPIError, match="immutable"):
                    with session.begin_nested():
                        session.execute(text(sql))
            session.rollback()
        with pytest.raises(RuntimeError, match="populated"):
            command.downgrade(config, "20261022_0064")
    finally:
        engine.dispose()
