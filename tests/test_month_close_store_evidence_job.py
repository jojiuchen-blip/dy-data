"""The scheduler, calculation and publication guards must use one historical version."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from apps.api.dy_api.models import DimStore, JobRun, SettlementMonthClose, SettlementStatement
from apps.worker import month_close, settlement_rebuild
from apps.worker.account_qualification import frozen_version
from apps.worker.billing_source_capture import BillingSourceDriftError
from apps.worker.monthly_store_evidence import freeze_store_evidence
from test_month_close_auto_bootstrap import MONTH, NOW, _quiet_sqlite_progress, _seed
from test_month_close_auto_bootstrap import bootstrap_session  # noqa: F401


def test_queued_close_keeps_its_mapping_until_a_new_job_is_created(bootstrap_session, monkeypatch):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    job_id = month_close.ensure_month_close_job(factory, now=NOW)
    assert job_id
    with factory.begin() as session:
        job = session.get(JobRun, job_id)
        initial = job.metadata_json["store_evidence_version_id"]
        qualification = frozen_version(session, MONTH)
        session.add(DimStore(store_id="second-store", store_name="Second store",
                             created_at=datetime(2026, 9, 1, tzinfo=UTC)))
        session.flush()
        updated = freeze_store_evidence(session, qualification_version=qualification, facts=[{
            "kind": "account", "key": "owner-dual", "store_id": "second-store",
            "source_reference": "synthetic/dated-account-directory", "source_sha256": "a" * 64,
            "observed_at": "2026-10-30T00:00:00Z", "valid_from": "2026-10-01", "valid_to": "2026-10-31",
        }])
        assert updated.version_id != initial
    # Each check gets a fresh session, as do the calculation and publication transactions.
    for _ in range(2):
        with factory() as session:
            settlement_rebuild._verify_month_calculation_input(session, MONTH, session.get(JobRun, job_id))
            assert session.info["monthly_store_evidence_version_id"] == initial
    with factory.begin() as session:
        job = session.get(JobRun, job_id)
        job.status = "failed"
    next_id = month_close.ensure_month_close_job(factory, now=NOW)
    assert next_id and next_id != job_id
    with factory() as session:
        assert session.get(JobRun, next_id).metadata_json["store_evidence_version_id"] == updated.version_id
        assert session.get(JobRun, job_id).metadata_json["store_evidence_version_id"] == initial


@pytest.mark.parametrize("field", ["store_evidence_version_id", "store_evidence_sha256"])
def test_close_rejects_missing_or_inconsistent_mapping_before_writing_bills(bootstrap_session, monkeypatch, field):
    monkeypatch.setenv("SETTLEMENT_MONTHLY_MODE", "true")
    factory = _seed(bootstrap_session)
    _quiet_sqlite_progress(monkeypatch, bootstrap_session)
    job_id = month_close.ensure_month_close_job(factory, now=NOW)
    with factory.begin() as session:
        job = session.get(JobRun, job_id)
        job.metadata_json = {**job.metadata_json, field: None}
    with pytest.raises(BillingSourceDriftError, match="store evidence"):
        settlement_rebuild.run_settlement_month_rebuild_job(factory=factory, job_id=job_id, business_month=MONTH)
    with factory() as session:
        assert session.get(SettlementMonthClose, MONTH) is None
        assert session.scalar(select(SettlementStatement.statement_id)) is None
