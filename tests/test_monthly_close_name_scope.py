"""Certify only the finite store impact proven by the frozen sales-name source."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    DimStorePoiMapping, JobRun, RawDouyinOrder, RawDouyinVerifyRecord,
    SettlementFeeResult, SettlementFeeResultCurrent, SettlementMonthClose,
)
from apps.worker import account_qualification as qualification, month_close, settlement, settlement_rebuild
from apps.worker.monthly_close_scope import (
    _exact_issue_stores, inspect_month_close_scope, monthly_fee_evidence_condition,
)
from apps.worker.repositories import upsert_aweme_account, upsert_store, upsert_store_poi_mapping, upsert_verify_record
from account_qualification_fixtures import binding
from test_certified_month_close import _bills, _close
from test_data_settlement import _dual_time, _load_dual_fee_fixture
from test_month_close_auto_bootstrap import MONTH, NOW, _quiet_sqlite_progress, _seed
from test_month_close_auto_bootstrap import bootstrap_session  # noqa: F401
from test_protected_billing_authority_postgres import postgres_engine  # noqa: F401


def test_certified_names_produce_fees_without_an_id_bridge(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    with factory.begin() as writer:
        upsert_store(writer, "wrong-live-store", "Wrong live store")
        upsert_aweme_account(writer, "owner-dual", store_id="wrong-live-store", binding_status="active")
        for order in writer.scalars(select(RawDouyinOrder)):
            order.owner_account_id = "opaque-transfer-id"
            order.raw_payload = {**order.raw_payload, "sale_info": {"transfer_uid": "opaque-transfer-id"}}
    _close(factory)
    with factory() as reader:
        assert reader.get(SettlementMonthClose, MONTH).is_complete
        assert {store: values[2:] for store, values in _bills(reader).items()} == {
            "store-sale": (6000, 0), "store-verify": (0, 4000),
        }
        results = list(reader.scalars(select(SettlementFeeResult).join(
            SettlementFeeResultCurrent, SettlementFeeResultCurrent.fee_result_id == SettlementFeeResult.fee_result_id,
        )))
        assert len(results) == 4
        assert {result.sale_account_match_json["policy"] for result in results} == {
            qualification.SALE_ACCOUNT_MATCH_POLICY,
        }
        assert {result.sale_account_match_json["store_id"] for result in results} == {"store-sale"}


def test_ambiguous_accounts_with_proven_store_impact_do_not_block_other_stores(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    records = [binding(), binding(account="other-account", douyin="other-dy", poi="other-poi", nickname="Other Sales"),
               binding(account="third-account", douyin="third-dy", poi="other-poi", nickname="Other Sales")]
    factory = _seed(bootstrap_session, records=records)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    with factory.begin() as writer:
        upsert_store(writer, "other-store", "Other Store")
        upsert_store_poi_mapping(writer, "other-store", "other-poi", mapping_source="test")
        order = writer.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-middle"))
        order.owner_account_name = "Other Sales"
        order.raw_payload = {**order.raw_payload, "owner_account_name": "Other Sales"}
        writer.get(RawDouyinVerifyRecord, "verify-middle").poi_id = "other-poi"
    _close(factory)
    with factory() as reader:
        scope = reader.get(SettlementMonthClose, MONTH)
        assert (scope.is_complete, scope.blocked_store_ids, scope.unscoped_issue_count) == (False, ["other-store"], 0)
        assert {store: values[2:] for store, values in _bills(reader).items()} == {
            "store-sale": (3000, 0), "store-verify": (0, 2000),
        }


def test_unmapped_frozen_candidate_retains_unbounded_impact(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    with factory.begin() as writer:
        mapping = writer.scalar(select(DimStorePoiMapping).where(DimStorePoiMapping.poi_id == "poi-sale"))
        writer.delete(mapping)
    _close(factory)
    with factory() as reader:
        scope = reader.get(SettlementMonthClose, MONTH)
        assert not scope.is_complete and scope.unscoped_issue_count
        assert _bills(reader) == {}


def test_issue_impact_uses_the_closed_month_verification(bootstrap_session):
    _seed(bootstrap_session)
    qualification.freeze_month(bootstrap_session, MONTH, now=NOW)
    upsert_store(bootstrap_session, "future-store", "Future Store")
    upsert_store_poi_mapping(bootstrap_session, "future-store", "future-poi", mapping_source="test")
    upsert_verify_record(bootstrap_session, "november-verify", coupon_id="middle", verify_status="valid",
                         verify_time=datetime(2026, 11, 10, tzinfo=timezone.utc), poi_id="future-poi",
                         sku_id="sku-dual", source_run_id="future-observation")
    assert _exact_issue_stores(bootstrap_session, "middle", 2, month=MONTH, verify_id=None) == {"store-verify"}
    assert _exact_issue_stores(bootstrap_session, "middle", 1, month=MONTH, verify_id=None) == {"store-sale"}


@pytest.mark.parametrize("invalid", [None, {"policy": "prior-id-policy"}, {"qualification_version_id": "other-version"},
                                  {"content_sha256": "0" * 64}, {"store_id": "wrong-store"}, {"douyin_id": ""},
                                  {"source_field": "verifier_name"}])
def test_same_qualification_version_cannot_validate_unproven_fee_attribution(db_session, invalid):
    _seed(db_session)
    version = qualification.freeze_month(db_session, MONTH, now=NOW)
    settlement.rebuild_dual_fee_results(db_session, calculation_run_id="calculate-name-basis", accounting_month=MONTH)
    fee = db_session.scalar(select(SettlementFeeResult).join(
        SettlementFeeResultCurrent, SettlementFeeResultCurrent.fee_result_id == SettlementFeeResult.fee_result_id,
    ).where(SettlementFeeResult.fee_direction == 1))
    assert fee is not None
    fee.sale_account_match_json = None if invalid is None else {**fee.sale_account_match_json, **invalid}
    db_session.flush()
    assert db_session.scalar(select(SettlementFeeResult.fee_result_id).where(
        SettlementFeeResult.fee_result_id == fee.fee_result_id, monthly_fee_evidence_condition(version),
    )) is None
    with pytest.raises(qualification.AccountQualificationError, match="current_fee_sale_name_basis_mismatch"):
        month_close.require_current_month_qualification(db_session, MONTH)
    scope = inspect_month_close_scope(db_session, month=MONTH, calculation_run_id="calculate-name-basis",
                                     qualification_version_id=version.version_id, coupon_ids=("coupon-dual", "middle"))
    assert scope.unscoped_issue_count
    assert fee.sale_store_id in scope.blocked_store_ids


def test_relevant_raw_sale_name_change_invalidates_queued_input(db_session):
    _seed(db_session)
    qualification.freeze_month(db_session, MONTH, now=NOW)
    revisions = month_close.published_days_revisions(db_session, MONTH)
    first = month_close._calculation_inputs_digest(db_session, MONTH, revisions, monthly=True)
    order = db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-middle"))
    order.raw_payload = {**order.raw_payload, "owner_account_name": "Changed original sales name"}
    db_session.flush()
    assert month_close._calculation_inputs_digest(db_session, MONTH, revisions, monthly=True) != first


def test_frozen_roster_poi_mapping_is_part_of_the_calculation_input(db_session):
    _seed(db_session)
    version = qualification.freeze_month(db_session, MONTH, now=NOW)
    for order in db_session.scalars(select(RawDouyinOrder)):
        order.owner_account_id = "opaque-transfer-id"
    db_session.flush()
    revisions = month_close.published_days_revisions(db_session, MONTH)
    first = month_close._calculation_inputs_digest(db_session, MONTH, revisions, monthly=True)
    upsert_store(db_session, "different-store", "Different Store")
    mapping = db_session.scalar(select(DimStorePoiMapping).where(DimStorePoiMapping.poi_id == "poi-sale"))
    mapping.store_id = "different-store"
    db_session.flush()
    assert version.content_sha256 == qualification.frozen_version(db_session, MONTH).content_sha256
    assert month_close._calculation_inputs_digest(db_session, MONTH, revisions, monthly=True) != first


def test_disabled_monthly_path_cannot_publish_successful_subset_of_october(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "false")
    factory = _seed(bootstrap_session)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    with factory.begin() as writer:
        order = writer.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "order-middle"))
        order.owner_account_name = None
        order.raw_payload = {"receipt_amount": 10001}
    job_id = month_close.ensure_month_close_job(factory, now=NOW)
    with pytest.raises(settlement_rebuild.SettlementSourceNotReady, match="certified store-scoped monthly close"):
        settlement_rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=job_id, business_month=MONTH)
    with factory() as reader:
        assert _bills(reader) == {}
        assert list(reader.scalars(select(SettlementFeeResultCurrent))) == []


@pytest.mark.parametrize("gate", ("disabled", "old-policy"))
def test_previously_queued_certified_jobs_obey_current_activation_and_policy(bootstrap_session, monkeypatch, gate):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    job_id = month_close.ensure_month_close_job(factory, now=NOW)
    if gate == "disabled":
        monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "false")
        message = "certified monthly close is not enabled"
    else:
        with factory.begin() as writer:
            job = writer.get(JobRun, job_id)
            job.metadata_json = {**job.metadata_json, "monthly_close_policy": "monthly-billing-v2"}
        message = "monthly close policy changed"
    with pytest.raises(settlement_rebuild.SettlementSourceNotReady, match=message):
        settlement_rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=job_id, business_month=MONTH)
    with factory() as reader:
        assert _bills(reader) == {}
        assert list(reader.scalars(select(SettlementFeeResultCurrent))) == []


@pytest.mark.parametrize("month", ("2026-08", "2026-09"))
def test_monthly_activation_retains_legacy_historical_month_runner(bootstrap_session, monkeypatch, month):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    _load_dual_fee_fixture(bootstrap_session)
    if month == "2026-08":
        bootstrap_session.get(RawDouyinVerifyRecord, "verify-coupon-dual").verify_time = _dual_time(8, 20)
    job_id = "approved-historical-month-" + month
    bootstrap_session.add(JobRun(job_id=job_id, job_name="settlement_rebuild", status="queued"))
    bootstrap_session.commit()
    factory = sessionmaker(bind=bootstrap_session.get_bind(), autoflush=False, expire_on_commit=False)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    assert settlement_rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=job_id, business_month=month)
    with factory() as reader:
        assert reader.get(JobRun, job_id).status == "success"
        assert {result.original_business_month for result in reader.scalars(select(SettlementFeeResult))} == {month}


def test_postgres_same_version_missing_name_proof_stays_unpublished(postgres_engine):
    with Session(postgres_engine, autoflush=False) as session:
        test_same_qualification_version_cannot_validate_unproven_fee_attribution(session, None)


def test_postgres_name_ambiguity_isolates_all_proven_candidate_stores(postgres_engine, monkeypatch):
    with Session(postgres_engine, autoflush=False) as session:
        test_ambiguous_accounts_with_proven_store_impact_do_not_block_other_stores(session, monkeypatch)
