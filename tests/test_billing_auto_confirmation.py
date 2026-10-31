"""Overdue confirmation uses bill month, exact source state and durable holds."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, event, func, select, insert
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    FinanceOperationAudit, JobRun, SettlementDispute, SettlementFeeResult,
    SettlementFeeResultCurrent, SettlementMonthlyOverlay, SettlementStatement,
    SettlementProjectionGeneration,
    SettlementStatementConfirmation, SettlementFeeAdjustment, SettlementStatementEntry,
    SettlementStatementLine,
    DimStore, SettlementProjectionActive, SettlementProjectionPartitionManifest,
)
from apps.worker import billing_auto_confirmation as service
from test_billing_statement_generation import _seed, _module

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)


@pytest.fixture()
def ready_bills(db_session, monkeypatch):
    return seed_ready_bills(db_session, monkeypatch)


def seed_ready_bills(db_session, monkeypatch):
    """Create real economic sources and a matching published immutable bill."""
    sources = _seed(db_session)
    db_session.get(SettlementProjectionGeneration, "billing-g1").published_at = NOW - timedelta(days=1)
    db_session.add(JobRun(job_id="synthetic-finalize", job_name="synthetic-finalize", status="success",
        finished_at=NOW - timedelta(days=2)))
    for source in sources:
        db_session.add(SettlementFeeResult(fee_result_id=source.source_record_id,
            coupon_id=source.coupon_id, order_id=source.order_id, fee_direction=source.fee_direction,
            original_business_month=source.original_business_month, rule_match_date=date(2026, 8, 1),
            sale_store_id=source.store_id, verify_store_id=source.store_id, sku_id="synthetic-sku",
            product_scope=source.product_scope, product_type=source.product_type,
            sale_channel_normalized="live", source_amount_cent=10000, fee_base_cent=10000,
            fee_amount_cent=1000, fee_rate="0.1", rule_version="v1", scope_rule_version="scope1",
            calculation_run_id="synthetic-calculation", calculated_at=NOW))
        db_session.add(SettlementFeeResultCurrent(coupon_id=source.coupon_id, fee_direction=source.fee_direction,
            fee_result_id=source.source_record_id))
    db_session.commit()
    _module().generate_pending_statements(db_session, generation_id="billing-g1", sources=sources)
    db_session.commit()
    # The real collection verifier is tested separately below. These cases
    # freeze only that independent signal, while exercising all financial SQL.
    monkeypatch.setattr(service, "published_days_revisions", lambda session, month: [month + "@synthetic-finalize"])
    return sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)


@pytest.mark.parametrize("month,expected", [
    ("2026-09", "2026-10-06T16:00:00+00:00"),
    ("2026-12", "2027-01-06T16:00:00+00:00"),
    ("2027-01", "2027-02-06T16:00:00+00:00"),
])
def test_cutoff_is_next_month_seventh_shanghai(month, expected):
    assert service.confirmation_due_at(month).isoformat() == expected


@pytest.mark.parametrize("month", ["2026-1", "invalid", "2026-13"])
def test_cutoff_rejects_invalid_month(month):
    with pytest.raises(ValueError):
        service.confirmation_due_at(month)


def test_dry_run_then_commit_readback_and_no_duplicate(ready_bills):
    preview = service.preview_auto_confirmation(ready_bills, now=NOW)
    assert preview["counts"] == {"candidate": 2}, preview
    with ready_bills() as session:
        assert session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 0
    result = service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=preview["preview_hash"])
    assert result["confirmed_count"] == 2
    replay = service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=preview["preview_hash"])
    assert replay["replayed"] is True and replay["confirmed_count"] == 0 and replay["original_confirmed_count"] == 2
    with ready_bills() as session:
        rows = list(session.scalars(select(SettlementStatementConfirmation)))
        assert [(row.fee_direction, row.confirmed_amount_cent, row.confirmed_by) for row in rows] == [
            (1, 1000, "system:auto-confirmation"), (2, 1000, "system:auto-confirmation")]
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type == "AUTO_CONFIRM_STATEMENT")) == 2
    repeated = service.preview_auto_confirmation(ready_bills, now=NOW)
    assert repeated["counts"] == {"already_confirmed": 2}
    assert service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=repeated["preview_hash"])["confirmed_count"] == 0


def assert_replay_read_only_with_commit_hook(factory, mode):
    """A committed receipt replay must not enter before_commit or change facts."""
    preview = service.preview_auto_confirmation(factory, now=NOW)
    original = service.apply_auto_confirmation(factory, now=NOW, preview_hash=preview["preview_hash"])
    assert original["confirmed_count"] == 2

    def snapshot():
        with factory() as session:
            confirmations = [tuple(row) for row in session.execute(select(
                SettlementStatementConfirmation.confirmation_id,
                SettlementStatementConfirmation.fee_direction,
                SettlementStatementConfirmation.confirmed_amount_cent,
                SettlementStatementConfirmation.confirmed_at,
            ).order_by(SettlementStatementConfirmation.confirmation_id))]
            audits = [tuple(row) for row in session.execute(select(
                FinanceOperationAudit.audit_id, FinanceOperationAudit.operation_type,
                FinanceOperationAudit.after_snapshot, FinanceOperationAudit.request_payload_sha256,
                FinanceOperationAudit.occurred_at,
            ).order_by(FinanceOperationAudit.audit_id))]
            return confirmations, audits

    before = snapshot()
    attempted = []
    values = dict(audit_id="synthetic-replay-hook", operation_type="SYNTHETIC_REPLAY_HOOK",
        target_type="SYNTHETIC", target_id="synthetic-target", operator_id="synthetic-test",
        operator_role=1, result_status=1, request_id="synthetic-replay-hook")

    def inject(session):
        attempted.append(service._DEADLINE_KEY in session.info)
        if mode == "orm":
            session.add(FinanceOperationAudit(**values))
        else:
            session.execute(insert(FinanceOperationAudit).values(**values))

    event.listen(Session, "before_commit", inject)
    try:
        replay = service.apply_auto_confirmation(factory, now=NOW, preview_hash=preview["preview_hash"])
    finally:
        event.remove(Session, "before_commit", inject)
    assert attempted == []
    assert replay["replayed"] is True and replay["confirmed_count"] == 0
    assert replay["original_confirmed_count"] == original["confirmed_count"]
    assert set(replay["confirmation_ids"]) == {row["confirmation_id"] for row in original["confirmed"]}
    assert snapshot() == before


@pytest.mark.parametrize("mode", ["orm", "sql"])
def test_replay_read_only_never_runs_commit_hooks(ready_bills, mode):
    assert_replay_read_only_with_commit_hook(ready_bills, mode)


def seed_negative_adjustments(factory):
    """Keep source facts, all published dimensions and every bill layer consistent."""
    with factory.begin() as session:
        bill = session.scalar(select(SettlementStatement))
        for direction, prefix in ((1, "promotion"), (2, "management")):
            setattr(bill, f"{prefix}_adjustment_fee_cent", -2000)
            setattr(bill, f"{prefix}_net_fee_cent", -1000)
            for aggregate in session.scalars(select(SettlementMonthlyOverlay)):
                setattr(aggregate, f"{prefix}_adjustment_fee_cent", -2000)
                setattr(aggregate, f"{prefix}_net_fee_cent", -1000)
            line = session.scalar(select(SettlementStatementLine).where(SettlementStatementLine.fee_direction == direction))
            line.adjustment_entry_count, line.adjustment_fee_cent, line.net_fee_cent = 1, -2000, -1000
            adjustment_id = f"synthetic-negative-adjustment-{direction}"
            session.add(SettlementFeeAdjustment(adjustment_id=adjustment_id, original_fee_result_id=f"fee-{direction}",
                coupon_id="coupon", order_id="order", fee_direction=direction, original_business_month="2026-08",
                adjustment_posting_month="2026-08", adjustment_type=1, adjustment_fee_cent=-2000,
                rule_version="v1", adjustment_reason="synthetic negative balance", occurred_at=NOW, created_by="test"))
            session.add(SettlementStatementEntry(statement_entry_id=f"negative-entry-{direction}",
                statement_id=bill.statement_id, statement_line_id=line.statement_line_id, source_type=2,
                source_record_id=adjustment_id, original_fee_result_id=f"fee-{direction}", coupon_id="coupon", order_id="order",
                fee_direction=direction, original_business_month="2026-08", statement_posting_month="2026-08",
                product_scope="scope", product_type="type", base_amount_cent=0, fee_amount_cent=-2000, rule_version="v1"))


def test_negative_management_and_signed_promotion_use_same_manual_contract(ready_bills):
    seed_negative_adjustments(ready_bills)
    from dy_api.routes.dashboard import _statement_confirmable_amounts, _statement_header_item
    with ready_bills() as session:
        bill = session.scalar(select(SettlementStatement))
        assert _statement_confirmable_amounts(session, bill) == {"PROMOTION": -1000, "MANAGEMENT": 0}
    preview = service.preview_auto_confirmation(ready_bills, now=NOW)
    assert preview["counts"] == {"candidate": 2}
    assert [(row["amount_cent"], row["statement_amount_cent"]) for row in preview["rows"]] == [(-1000, -1000), (0, -1000)]
    result = service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=preview["preview_hash"])
    assert result["confirmed_count"] == 2
    with ready_bills() as session:
        header = _statement_header_item(session, session.scalar(select(SettlementStatement)))
        assert header["promotion_confirmation"]["confirmed_amount_cent"] == -1000
        assert header["management_confirmation"]["confirmed_amount_cent"] == 0
    replay = service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=preview["preview_hash"])
    assert replay["replayed"] is True and replay["confirmed_count"] == 0


def test_deadline_before_and_after_and_late_generated_bill(ready_bills):
    due = service.confirmation_due_at("2026-08")
    before = service.preview_auto_confirmation(ready_bills, now=due - timedelta(microseconds=1))
    assert before["counts"] == {"not_due": 2}
    at_boundary = service.preview_auto_confirmation(ready_bills, now=due)
    assert at_boundary["counts"] == {"candidate": 2}
    with ready_bills.begin() as session:
        session.scalar(select(SettlementStatement)).created_at = NOW
    # Late generation does not reopen the already elapsed original window.
    assert service.preview_auto_confirmation(ready_bills, now=NOW)["counts"] == {"candidate": 2}


def test_incomplete_real_collection_signal_blocks(ready_bills, monkeypatch):
    from apps.worker.month_close import published_days_revisions
    monkeypatch.setattr(service, "published_days_revisions", published_days_revisions)
    preview = service.preview_auto_confirmation(ready_bills, now=NOW)
    assert {row["reason"] for row in preview["rows"]} == {"SOURCE_INCOMPLETE"}


@pytest.mark.parametrize("change,reason", [
    ("amount", "BILL_PUBLICATION_MISMATCH"),
    ("source", "BILL_SOURCE_VERSION_MISMATCH"),
    ("active", "PUBLICATION_NOT_READY"),
    ("locked", "STATEMENT_LOCKED"),
    ("busy", "SOURCE_JOB_ACTIVE"),
    ("queued", "SOURCE_JOB_ACTIVE"),
    ("new_collection", "COLLECTION_NEWER_THAN_PUBLICATION"),
])
def test_unsafe_state_has_explicit_refusal_and_zero_confirmation(ready_bills, change, reason):
    with ready_bills.begin() as session:
        bill = session.scalar(select(SettlementStatement))
        if change == "amount":
            for aggregate in session.scalars(select(SettlementMonthlyOverlay)):
                aggregate.promotion_original_fee_cent = aggregate.promotion_net_fee_cent = 999
        elif change == "source":
            row = session.scalar(select(SettlementFeeResult).where(SettlementFeeResult.fee_direction == 1))
            row.fee_amount_cent = 999
        elif change == "active":
            from apps.api.dy_api.models import SettlementProjectionActive
            session.scalar(select(SettlementProjectionActive)).generation_id = None
        elif change == "locked":
            bill.locked_at = NOW
        elif change == "new_collection":
            session.get(JobRun, "synthetic-finalize").finished_at = NOW
        else:
            session.add(JobRun(job_id="running-rebuild", job_name="settlement_rebuild", status="queued" if change == "queued" else "running"))
    preview = service.preview_auto_confirmation(ready_bills, now=NOW)
    assert {row["reason"] for row in preview["rows"]} == {reason}
    assert service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=preview["preview_hash"])["confirmed_count"] == 0


def test_one_disputed_direction_does_not_block_other(ready_bills):
    with ready_bills.begin() as session:
        bill = session.scalar(select(SettlementStatement))
        session.add(SettlementDispute(dispute_id="synthetic-dispute", statement_id=bill.statement_id,
            store_id=bill.store_id, statement_month=bill.statement_month, fee_direction=2,
            dispute_type=1, status=1, description="synthetic", contact_name="synthetic",
            contact_phone_ciphertext="synthetic", submitted_by="synthetic"))
    preview = service.preview_auto_confirmation(ready_bills, now=NOW)
    assert [(row["direction"], row["state"], row["reason"]) for row in preview["rows"]] == [
        (1, "candidate", None), (2, "blocked", "DISPUTE_PROTECTED")]
    assert service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=preview["preview_hash"])["confirmed_count"] == 1


def test_hold_and_explicit_release_are_durable_audited_and_idempotent(ready_bills):
    values = dict(store_id="billing-store", month="2026-08", direction=1,
        reason="pending reviewed correction", evidence_reference="synthetic-review", operator="test-admin")
    with ready_bills.begin() as session:
        first = service.set_confirmation_hold(session, **values, active=True, request_key="hold-1")
        again = service.set_confirmation_hold(session, **values, active=True, request_key="hold-1")
        assert first.audit_id == again.audit_id
    held = service.preview_auto_confirmation(ready_bills, now=NOW)
    assert held["rows"][0]["reason"] == "EXPLICIT_REVIEW_HOLD"
    assert held["rows"][1]["state"] == "candidate"
    with ready_bills.begin() as session:
        service.set_confirmation_hold(session, **values, active=False, request_key="release-1")
    assert service.preview_auto_confirmation(ready_bills, now=NOW)["counts"] == {"candidate": 2}
    with ready_bills() as session:
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type == service.HOLD_OPERATION)) == 2


def test_manual_confirmation_after_preview_rejects_whole_stale_apply(ready_bills):
    preview = service.preview_auto_confirmation(ready_bills, now=NOW)
    with ready_bills.begin() as session:
        bill = session.scalar(select(SettlementStatement))
        session.add(SettlementStatementConfirmation(confirmation_id="synthetic-manual",
            statement_id=bill.statement_id, fee_direction=1, confirmed_amount_cent=1000,
            confirmed_by="manual-user", confirmed_at=NOW))
    with pytest.raises(service.AutoConfirmationConflict, match="preview changed"):
        service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=preview["preview_hash"])
    with ready_bills() as session:
        assert session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 1


def test_hold_change_after_preview_rejects_apply(ready_bills):
    preview = service.preview_auto_confirmation(ready_bills, now=NOW)
    with ready_bills.begin() as session:
        service.set_confirmation_hold(session, store_id="billing-store", month="2026-08", direction=2,
            active=True, reason="new dispute evidence", evidence_reference="synthetic-review",
            operator="test-admin", request_key="new-hold")
    with pytest.raises(service.AutoConfirmationConflict):
        service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=preview["preview_hash"])


def test_scheduler_default_off_and_enabled_compensation_is_observable(ready_bills, monkeypatch):
    monkeypatch.delenv("BILLING_AUTO_CONFIRM_ENABLED", raising=False)
    assert service.process_due_auto_confirmations(object()) is False
    monkeypatch.setenv("BILLING_AUTO_CONFIRM_ENABLED", "true")
    assert service.process_due_auto_confirmations(ready_bills) is True
    assert service.process_due_auto_confirmations(ready_bills) is False
    with ready_bills() as session:
        job = session.scalar(select(JobRun).where(JobRun.job_name == "billing_auto_confirmation"))
        assert job.status == "success" and job.metadata_json["confirmed_count"] == 2


def test_scheduler_failure_is_recorded_and_retried_with_backoff(ready_bills, monkeypatch):
    monkeypatch.setenv("BILLING_AUTO_CONFIRM_ENABLED", "true")
    def fail(*args, **kwargs):
        raise service.AutoConfirmationConflict("synthetic source change")
    monkeypatch.setattr(service, "apply_auto_confirmation", fail)
    assert service.process_due_auto_confirmations(ready_bills) is True
    assert service.process_due_auto_confirmations(ready_bills) is False
    with ready_bills() as session:
        job = session.scalar(select(JobRun).where(JobRun.job_name == "billing_auto_confirmation"))
        assert job.status == "failed" and job.metadata_json["error_type"] == "AutoConfirmationConflict"
        assert session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 0


def seed_many_bills(factory, count):
    """Populate representative stores with real current fees and generated bills."""
    from apps.worker.settlement import StatementSource
    with factory.begin() as session:
        sources = []
        for index in range(1, count):
            store_id = f"batch-store-{index}"
            session.add(DimStore(store_id=store_id, store_name="Synthetic Batch Store"))
            for scope, product_type in (("all", "all"), ("all", "type"), ("scope", "all"), ("scope", "type")):
                session.add(SettlementMonthlyOverlay(generation_id="billing-g1", partition_key="2026-08", month="2026-08",
                    store_id=store_id, product_scope=scope, product_type=product_type,
                    promotion_base_cent=10000, promotion_original_fee_cent=1000, promotion_net_fee_cent=1000,
                    management_base_cent=10000, management_original_fee_cent=1000, management_net_fee_cent=1000))
            for direction in (1, 2):
                result_id, coupon_id, order_id = f"batch-fee-{index}-{direction}", f"batch-coupon-{index}", f"batch-order-{index}"
                session.add(SettlementFeeResult(fee_result_id=result_id, coupon_id=coupon_id, order_id=order_id,
                    fee_direction=direction, original_business_month="2026-08", rule_match_date=date(2026, 8, 1),
                    sale_store_id=store_id, verify_store_id=store_id, sku_id="synthetic-sku", product_scope="scope",
                    product_type="type", sale_channel_normalized="live", source_amount_cent=10000,
                    fee_base_cent=10000, fee_amount_cent=1000, fee_rate="0.1", rule_version="v1",
                    scope_rule_version="scope1", calculation_run_id="batch-calculation", calculated_at=NOW))
                session.add(SettlementFeeResultCurrent(coupon_id=coupon_id, fee_direction=direction, fee_result_id=result_id))
                sources.append(StatementSource(source_type=1, source_record_id=result_id, original_fee_result_id=result_id,
                    coupon_id=coupon_id, order_id=order_id, fee_direction=direction, original_business_month="2026-08",
                    posting_month="2026-08", store_id=store_id, product_scope="scope", product_type="type",
                    base_amount_cent=10000, fee_amount_cent=1000, source_amount_cent=10000, rule_version="v1"))
        session.flush()
        _module().generate_pending_statements(session, generation_id="billing-g1", sources=sources)


def test_one_five_fifty_bill_queries_are_bounded_and_authority_is_read_once(ready_bills, monkeypatch):
    seed_many_bills(ready_bills, 50)
    engine = ready_bills.kw["bind"]
    original = service._sparse_authority_relation
    calls, queries, counts = [], [], []
    monkeypatch.setattr(service, "_sparse_authority_relation", lambda months: calls.append(months) or original(months))
    def count(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            queries.append(statement)
    event.listen(engine, "before_cursor_execute", count)
    try:
        for size in (1, 5, 50):
            calls.clear()
            queries.clear()
            result = service.preview_auto_confirmation(ready_bills, now=NOW, limit=size)
            assert result["counts"] == {"candidate": size * 2}
            assert len(calls) == 1
            counts.append(len(queries))
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(set(counts)) == 1 and max(counts) <= 25, counts


def test_source_row_cap_refuses_before_writing(ready_bills, monkeypatch):
    preview = service.preview_auto_confirmation(ready_bills, now=NOW)
    monkeypatch.setattr(service, "MAX_BATCH_SOURCE_ROWS", 1)
    with pytest.raises(service.AutoConfirmationConflict, match="row limit"):
        service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=preview["preview_hash"])
    with ready_bills() as session:
        assert session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 0
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type.in_(("AUTO_CONFIRM_BATCH", "AUTO_CONFIRM_STATEMENT")))) == 0


def test_wall_budget_expiring_during_flush_rolls_back_all_directions(ready_bills, monkeypatch):
    preview = service.preview_auto_confirmation(ready_bills, now=NOW)
    clock, inserted = [0.0], []
    monkeypatch.setattr(service, "_wall_clock", lambda: clock[0])
    engine = ready_bills.kw["bind"]
    def expire(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO"):
            inserted.append(statement)
            clock[0] = 31.0
    event.listen(engine, "after_cursor_execute", expire)
    try:
        with pytest.raises(service.AutoConfirmationConflict, match="wall budget"):
            service.apply_auto_confirmation(ready_bills, now=NOW, preview_hash=preview["preview_hash"])
    finally:
        event.remove(engine, "after_cursor_execute", expire)
    assert inserted
    with ready_bills() as session:
        assert session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 0
        assert session.scalar(select(func.count()).select_from(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type.in_(("AUTO_CONFIRM_BATCH", "AUTO_CONFIRM_STATEMENT")))) == 0


def seed_zero_bill(factory, *, keep_audit=True):
    """Official generator may create an empty zero slot amid another store's overlay."""
    seed_many_bills(factory, 2)
    with factory.begin() as session:
        session.add(SettlementProjectionGeneration(generation_id="billing-g2", state="published", input_fingerprint="billing-g2",
            base_generation_id="billing-g1", lineage_depth=1, published_at=NOW - timedelta(days=1)))
        session.flush()
        session.get(SettlementProjectionActive, "settlement").generation_id = "billing-g2"
        session.add(SettlementProjectionPartitionManifest(generation_id="billing-g2", artifact="monthly",
            partition_key="2026-08", source_kind="overlay", data_generation_id="billing-g2", base_generation_id="billing-g1"))
        for scope, product_type in (("all", "all"), ("all", "type"), ("scope", "all"), ("scope", "type")):
            session.add(SettlementMonthlyOverlay(generation_id="billing-g2", partition_key="2026-08", month="2026-08",
                store_id="batch-store-1", product_scope=scope, product_type=product_type,
                promotion_base_cent=10000, promotion_original_fee_cent=1000, promotion_net_fee_cent=1000,
                management_base_cent=10000, management_original_fee_cent=1000, management_net_fee_cent=1000))
        session.execute(delete(SettlementFeeResultCurrent).where(SettlementFeeResultCurrent.coupon_id == "coupon"))
        session.flush()
        result = _module().generate_pending_statements(session, generation_id="billing-g2", sources=(),
            slots=(("billing-store", "2026-08"),))
        assert result["generated"] == 1 and result["blocked"] == 0
        if not keep_audit:
            current_id = session.scalar(select(SettlementStatement.statement_id).where(
                SettlementStatement.store_id == "billing-store", SettlementStatement.is_current.is_(True)))
            session.execute(delete(FinanceOperationAudit).where(FinanceOperationAudit.target_id == current_id))


@pytest.mark.parametrize("keep_audit", [True, False])
def test_missing_target_overlay_only_becomes_zero_with_exact_empty_generation_evidence(ready_bills, keep_audit):
    seed_zero_bill(ready_bills, keep_audit=keep_audit)
    preview = service.preview_auto_confirmation(ready_bills, now=NOW, store_ids=("billing-store",))
    assert [row["amount_cent"] for row in preview["rows"]] == [0, 0]
    if keep_audit:
        assert preview["counts"] == {"candidate": 2}
        assert service.apply_auto_confirmation(ready_bills, now=NOW, store_ids=("billing-store",),
            preview_hash=preview["preview_hash"])["confirmed_count"] == 2
    else:
        assert {row["reason"] for row in preview["rows"]} == {"BILL_SOURCE_EVIDENCE_MISSING"}
