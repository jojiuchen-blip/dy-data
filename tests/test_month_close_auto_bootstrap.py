"""Month-end freeze dispatches real month calculation before any fee is pinned."""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    AccountQualificationVersion, DataQualityIssue, DimStore, JobImpact, JobRun,
    RawDouyinOrder, RawDouyinVerifyRecord, SettlementFeeResult, SettlementFeeResultCurrent,
    SettlementProjectionActive, SettlementProjectionGeneration, SettlementStatement, SkuFeeRule,
)
from apps.worker import account_qualification as q, month_close as close, settlement, settlement_rebuild as rebuild
from apps.worker.repositories import upsert_raw_order, upsert_order_coupon, upsert_verify_record
from account_qualification_fixtures import binding, observe
from test_data_settlement import _load_dual_fee_fixture, _add_scope_rule, _dual_time
from test_month_close import _publish_day

MONTH = "2026-10"
NOW = datetime(2026, 11, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def bootstrap_session(tmp_path):
    from apps.api.dy_api.models import Base

    # Legacy progress heartbeats use independent sessions. A shared in-memory
    # StaticPool would let their commits also commit the writer's transaction.
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "bootstrap.sqlite"),
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    engine.dispose()


def _seed(session, *, legacy=False, records=None, days=True, base=True):
    _load_dual_fee_fixture(session)
    if legacy:
        settlement.rebuild_dual_fee_results(session, calculation_run_id="legacy-september")
        for fee in session.scalars(select(SettlementFeeResult)):
            fee.original_business_month = MONTH
            fee.rule_match_date = _dual_time(10, 5).date()
            fee.qualifying_verify_time = _dual_time(10, 5)
    session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(10, 5)
    _add_scope_rule(session, MONTH)
    upsert_raw_order(session, "order-middle", order_status="paid", order_status_normalized="paid",
        sku_id="sku-dual", pay_time=_dual_time(8, 10), sale_time=_dual_time(8, 10),
        owner_account_id="owner-dual", owner_account_name="Owner Dual", sale_channel="short_video",
        sale_channel_normalized="short_video", raw_payload={"receipt_amount": 10001}, source_run_id="source-middle")
    upsert_order_coupon(session, "middle", "order-middle", coupon_status="fulfilled", coupon_status_normalized="available",
        coupon_paid_amount_cent=10001, coupon_refunded_amount_cent=0, source_run_id="source-middle")
    upsert_verify_record(session, "verify-middle", coupon_id="middle", verify_status="valid", verify_time=_dual_time(10, 20),
        poi_id="poi-verify", sku_id="sku-dual", source_run_id="source-middle")
    observe(session, records=records)
    if days:
        for day in close.month_business_dates(MONTH):
            _publish_day(session, day)
    if base:
        session.add(SettlementProjectionGeneration(generation_id="bootstrap-base", state="published", input_fingerprint="f" * 64))
        session.flush()
        session.add(SettlementProjectionActive(projection_name="settlement", generation_id="bootstrap-base"))
    session.commit()
    return sessionmaker(bind=session.get_bind(), autoflush=False, expire_on_commit=False)


def _current(session):
    session.expire_all()
    return list(session.scalars(select(SettlementFeeResult).join(SettlementFeeResultCurrent,
        SettlementFeeResultCurrent.fee_result_id == SettlementFeeResult.fee_result_id)))


def _financial_facts(session):
    session.expire_all()
    from apps.api.dy_api.models import Base
    return {table.name: sorted(repr(tuple(row)) for row in session.execute(select(table)))
            for table in Base.metadata.sorted_tables
            if table.name.startswith(("settlement_fee", "settlement_statement", "agg_store", "invoice", "promotion_invoice"))}


def _quiet_sqlite_progress(monkeypatch, session):
    # SQLite permits one writer. Stub only heartbeat progress for the legacy
    # transaction tests; fee selection, calculation, commit fence and guard are real.
    if session.get_bind().dialect.name != "sqlite":
        return
    @contextmanager
    def watchdog(*args, **kwargs):
        yield lambda *args: None
    monkeypatch.setattr(rebuild, "_settlement_rebuild_heartbeat_watchdog", watchdog)


@pytest.mark.parametrize("legacy", (False, True))
def test_freeze_automatically_bootstraps_whole_month_actual_rebuild_and_publication(db_session, legacy, monkeypatch):
    factory = _seed(db_session, legacy=legacy)
    if not legacy:
        class Midmonth(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 15, tzinfo=timezone.utc).astimezone(tz)
        with monkeypatch.context() as context:
            context.setattr(q, "datetime", Midmonth)
            settlement.rebuild_dual_fee_results(db_session, calculation_run_id="ordinary-midmonth-zero")
        db_session.commit()
        assert _current(db_session) == []
    assert db_session.scalar(select(func.count()).select_from(AccountQualificationVersion)) == 0
    assert close.month_source_watermark(db_session, MONTH) is None
    impacts = db_session.scalar(select(func.count()).select_from(JobImpact))
    job_id = close.ensure_month_close_job(factory, now=NOW)
    assert job_id and close.ensure_month_close_job(factory, now=NOW) == job_id
    db_session.expire_all()
    version = db_session.scalar(select(AccountQualificationVersion))
    job = db_session.get(JobRun, job_id)
    assert job.status == "queued" and job.metadata_json["business_month"] == MONTH
    assert job.metadata_json["account_qualification_version_id"] == version.version_id
    assert db_session.scalar(select(func.count()).select_from(JobImpact)) == impacts
    # Public readiness never pretends that dispatch has already produced fees.
    assert close.month_source_watermark(db_session, MONTH) is None
    assert len(close.published_days_revisions(db_session, MONTH)) == 31
    assert rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=job_id, business_month=MONTH)
    rows = _current(db_session)
    assert {(row.coupon_id, row.fee_direction) for row in rows} == {
        (coupon, direction) for coupon in ("coupon-dual", "middle") for direction in (1, 2)}
    assert {row.account_qualification_version_id for row in rows} == {version.version_id}
    assert {row.original_business_month for row in rows} == {MONTH}
    assert {row.qualifying_verify_time.day for row in rows} == {5, 20}
    assert sum(row.fee_amount_cent for row in rows if row.fee_direction == 1) == 6000
    assert sum(row.fee_amount_cent for row in rows if row.fee_direction == 2) == 4000
    bills = db_session.scalars(select(SettlementStatement).where(SettlementStatement.is_current.is_(True)))
    assert {(row.store_id, row.promotion_net_fee_cent, row.management_net_fee_cent) for row in bills} == {
        ("store-sale", 6000, 0), ("store-verify", 0, 4000)}
    assert db_session.get(JobRun, job_id).status == "success"
    assert close.month_source_watermark(db_session, MONTH)
    # Recalculation output IDs are absent from the input key: no self-dispatch loop.
    assert close.ensure_month_close_job(factory, now=NOW) == job_id
    assert db_session.scalar(select(func.count()).select_from(JobRun).where(JobRun.job_name == "settlement_rebuild")) == 1


@pytest.mark.parametrize("kind", ("unknown", "explicitly-ineligible"))
def test_unapproved_old_current_fees_block_commit_and_publication(db_session, kind):
    records = [binding(account="other")] if kind == "unknown" else [binding(kind="个人号")]
    factory = _seed(db_session, legacy=True, records=records)
    job_id = close.ensure_month_close_job(factory, now=NOW)
    assert job_id
    before = _financial_facts(db_session)
    with pytest.raises(rebuild.SettlementSourceNotReady, match="current_fee_qualification_version_mismatch"):
        rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=job_id, business_month=MONTH)
    assert _financial_facts(db_session) == before
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == "bootstrap-base"
    assert close.month_source_watermark(db_session, MONTH) is None
    assert {row.account_qualification_version_id for row in _current(db_session)} == {None}


def test_input_digest_ignores_outputs_and_processing_times_but_tracks_relevant_receipt_and_rule(db_session):
    factory = _seed(db_session)
    first = close.ensure_month_close_job(factory, now=NOW)
    with factory.begin() as session:
        session.get(JobRun, first).status = "failed"
        session.get(JobRun, first).attempt_count = session.get(JobRun, first).max_attempts = 3
        order = session.get(RawDouyinOrder, 1)
        order.updated_at = NOW
        order.source_observed_at = NOW
        order.source_run_id = "different-processing-run"
        order.raw_payload = {**order.raw_payload, "irrelevant_large_field": "x" * 20000}
    assert close.ensure_month_close_job(factory, now=NOW) == first
    with factory.begin() as session:
        order = session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-coupon-dual"))
        order.raw_payload = {"receipt_amount": 20001}
    second = close.ensure_month_close_job(factory, now=NOW)
    assert second != first
    with factory.begin() as session:
        session.get(JobRun, second).status = "failed"
        rule = session.scalar(select(SkuFeeRule).where(SkuFeeRule.rule_version == "fee-sep"))
        rule.promotion_service_fee_rate = "0.25"
    assert close.ensure_month_close_job(factory, now=NOW) not in (first, second)


@pytest.mark.parametrize("reason", ("missing-day", "latest-failed", "active-job", "locked"))
def test_auto_bootstrap_never_bypasses_source_or_execution_guards(db_session, reason):
    factory = _seed(db_session)
    if reason == "missing-day":
        final_id = close.published_days_revisions(db_session, MONTH)[15].split("@", 1)[1]
        db_session.get(JobRun, final_id).status = "failed"
    elif reason == "latest-failed":
        _, cutoff = q.month_bounds(MONTH)
        identity = q.start_observation(db_session, source_run_id="last-attempt-failed", started_at=cutoff - timedelta(minutes=20))
        q.fail_observation(db_session, identity, error_code="synthetic", ended_at=cutoff - timedelta(minutes=10))
    elif reason == "active-job":
        db_session.add(JobRun(job_id="other-rebuild", job_name="settlement_rebuild", status="running"))
    else:
        db_session.add(SettlementStatement(statement_id="locked", store_id="store-sale", statement_month=MONTH, statement_status=4))
    db_session.commit()
    assert close.ensure_month_close_job(factory, now=NOW) is None
    assert db_session.scalar(select(func.count()).select_from(JobRun).where(JobRun.job_name == "settlement_rebuild")) == (1 if reason == "active-job" else 0)


def test_unrelated_month_does_not_change_bootstrap_hash_or_reset_failed_budget(db_session):
    factory = _seed(db_session)
    first = close.ensure_month_close_job(factory, now=NOW)
    with factory.begin() as session:
        job = session.get(JobRun, first)
        job.status, job.attempt_count, job.max_attempts = "failed", 3, 3
        upsert_raw_order(session, "unrelated-september", order_status="paid", sku_id="other-sku", raw_payload={"receipt_amount": 999})
        upsert_order_coupon(session, "unrelated", "unrelated-september", coupon_status="fulfilled")
        upsert_verify_record(session, "unrelated-verify", coupon_id="unrelated", verify_status="valid", verify_time=_dual_time(9, 5))
    assert close.ensure_month_close_job(factory, now=NOW) == first
    assert not rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=first, business_month=MONTH)
    db_session.expire_all()
    assert db_session.get(JobRun, first).attempt_count == 3


def test_same_failed_input_uses_normal_worker_retry_budget_without_new_scheduler_jobs(db_session):
    from apps.worker.queued_jobs import process_queued_settlement_rebuilds

    factory = _seed(db_session, legacy=True, records=[binding(account="other")])
    job_id = close.ensure_month_close_job(factory, now=NOW)
    before = _financial_facts(db_session)
    for attempt in (1, 2, 3):
        result = process_queued_settlement_rebuilds(factory, now=NOW)
        assert result.processed_job_id == job_id
        db_session.expire_all()
        job = db_session.get(JobRun, job_id)
        assert job.attempt_count == attempt
        assert job.status == ("failed" if attempt == 3 else "retry_wait")
        assert close.ensure_month_close_job(factory, now=NOW) == job_id
    assert process_queued_settlement_rebuilds(factory, now=NOW).processed_job_id is None
    assert _financial_facts(db_session) == before
    assert db_session.scalar(select(func.count()).select_from(JobRun).where(JobRun.job_name == "settlement_rebuild")) == 1


def test_bootstrap_queued_job_still_obeys_normal_resource_claim_admission(db_session, monkeypatch):
    from types import SimpleNamespace

    factory = _seed(db_session)
    job_id = close.ensure_month_close_job(factory, now=NOW)
    before = _financial_facts(db_session)
    monkeypatch.setattr(rebuild, "current_resource_decision", lambda: SimpleNamespace(action="stop"))
    assert not rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=job_id, business_month=MONTH)
    db_session.expire_all()
    assert db_session.get(JobRun, job_id).status == "queued"
    assert not db_session.get(JobRun, job_id).attempt_count
    assert close.ensure_month_close_job(factory, now=NOW) == job_id
    assert _financial_facts(db_session) == before


def test_retiring_old_current_does_not_change_raw_input_scope_or_create_new_budget(db_session):
    factory = _seed(db_session, legacy=True)
    order = db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-coupon-dual"))
    order.order_status_normalized = "closed"
    db_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(9, 5)
    db_session.commit()
    job_id = close.ensure_month_close_job(factory, now=NOW)
    with factory.begin() as session:
        job = session.get(JobRun, job_id)
        job.status, job.attempt_count, job.max_attempts = "failed", 3, 3
    revisions = close.published_days_revisions(db_session, MONTH)
    before = close._calculation_inputs_digest(db_session, MONTH, revisions)
    # Exercise ordinary fee retirement, without changing raw/configuration
    # inputs between the two fingerprints or inventing a fee-policy exception.
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="ordinary-retirement", coupon_ids=("coupon-dual",))
    db_session.commit()
    assert _current(db_session) == []
    assert close._calculation_inputs_digest(db_session, MONTH, revisions) == before
    assert close.ensure_month_close_job(factory, now=NOW) == job_id
    assert db_session.scalar(select(func.count()).select_from(JobRun).where(JobRun.job_name == "settlement_rebuild")) == 1


def test_changed_source_after_queue_fails_before_fee_mutation_then_dispatches_new_input(db_session):
    factory = _seed(db_session)
    first = close.ensure_month_close_job(factory, now=NOW)
    order = db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-middle"))
    order.raw_payload = {"receipt_amount": 20001}
    db_session.commit()
    before = _financial_facts(db_session)
    with pytest.raises(rebuild.SettlementSourceNotReady, match="calculation input changed"):
        rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=first, business_month=MONTH)
    assert _financial_facts(db_session) == before
    # Let the original normal failure budget finish. The scheduler cannot
    # create a new job while that retry remains active.
    assert close.ensure_month_close_job(factory, now=NOW) is None
    with factory.begin() as session:
        session.get(JobRun, first).status = "failed"
    assert close.ensure_month_close_job(factory, now=NOW) not in (None, first)


@pytest.mark.parametrize("frozen", (False, True))
def test_full_runner_without_active_pointer_rolls_back_unpinned_october_economics(bootstrap_session, frozen, monkeypatch):
    db_session = bootstrap_session
    _quiet_sqlite_progress(monkeypatch, db_session)
    factory = _seed(db_session, legacy=True, records=[binding(account="other")], base=False)
    if frozen:
        q.freeze_month(db_session, MONTH, now=NOW)
    db_session.add(JobRun(job_id="legacy-full", job_name="settlement_rebuild", status="queued"))
    db_session.commit()
    before = _financial_facts(db_session)
    with pytest.raises(rebuild.SettlementSourceNotReady, match="qualification publication blocked"):
        rebuild.run_settlement_rebuild_job(factory=factory, job_id="legacy-full")
    assert _financial_facts(db_session) == before
    assert db_session.get(JobRun, "legacy-full").status != "success"


def test_legacy_september_full_initialization_needs_no_october_freeze(bootstrap_session, monkeypatch):
    db_session = bootstrap_session
    _quiet_sqlite_progress(monkeypatch, db_session)
    _load_dual_fee_fixture(db_session)
    db_session.add(JobRun(job_id="september-full", job_name="settlement_rebuild", status="queued"))
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)
    assert rebuild.run_settlement_rebuild_job(factory=factory, job_id="september-full")
    assert {row.original_business_month for row in _current(db_session)} == {"2026-09"}
    assert db_session.scalar(select(func.count()).select_from(AccountQualificationVersion)) == 0


def test_publication_only_refuses_real_october_closure_but_keeps_august_september_usable(db_session):
    from test_protected_billing_authority import _seed as protected_seed
    from apps.worker.settlement_publication_only import apply_settlement_publication, preview_settlement_publication

    protected_seed(db_session, move_month=MONTH)
    db_session.add(SettlementProjectionGeneration(generation_id="august-base", state="published", input_fingerprint="e" * 64))
    db_session.flush()
    db_session.add(SettlementProjectionActive(projection_name="settlement", generation_id="august-base"))
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)
    assert preview_settlement_publication(factory, months=("2026-09",))["closure_months"] == ["2026-09"]
    before = _financial_facts(db_session)
    with pytest.raises(rebuild.SettlementSourceNotReady, match="monthend_version_missing"):
        preview_settlement_publication(factory, months=("2026-08",))
    with pytest.raises(rebuild.SettlementSourceNotReady, match="monthend_version_missing"):
        apply_settlement_publication(factory, months=("2026-08",), preview_hash="a" * 64)
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0
    assert _financial_facts(db_session) == before


def test_final_locked_capture_rejects_a_single_unpinned_fee_among_valid_results(db_session, monkeypatch):
    factory = _seed(db_session)
    first = close.ensure_month_close_job(factory, now=NOW)
    assert rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=first, business_month=MONTH)
    prior_generation = db_session.get(SettlementProjectionActive, "settlement", populate_existing=True).generation_id
    db_session.add(JobRun(job_id="later-month-publication", job_name="settlement_rebuild", status="queued"))
    db_session.commit()
    original_ready = rebuild.mark_settlement_sparse_overlay_ready
    def change_after_ready(*args, **kwargs):
        result = original_ready(*args, **kwargs)
        with factory.begin() as session:
            fee = session.scalar(select(SettlementFeeResult).join(SettlementFeeResultCurrent,
                SettlementFeeResultCurrent.fee_result_id == SettlementFeeResult.fee_result_id,
            ).where(SettlementFeeResult.coupon_id == "middle", SettlementFeeResult.fee_direction == 1))
            fee.account_qualification_version_id = None
        return result
    monkeypatch.setattr(rebuild, "mark_settlement_sparse_overlay_ready", change_after_ready)
    with pytest.raises(rebuild.SettlementSourceNotReady, match="current_fee_qualification_version_mismatch"):
        rebuild.run_settlement_month_rebuild_job(factory=factory, job_id="later-month-publication", business_month=MONTH)
    db_session.expire_all()
    assert len(_current(db_session)) == 4
    assert len([row for row in _current(db_session) if row.account_qualification_version_id]) == 3
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == prior_generation
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 2
