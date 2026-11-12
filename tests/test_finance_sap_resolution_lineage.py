"""Keep actual SAP decision provenance through same-value imports and reversal."""

import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import FinanceImportRow, FinanceOperationAudit, SapSuggestion, StoreFinanceProfile
from test_api_finance_imports import _login, _upload, client  # noqa: F401
from dy_api.routes import dashboard as dashboard_routes
from test_dydata104_finance_state_matrix import db_session  # noqa: F401


DECIDED_AT = datetime(2026, 8, 22, 10, tzinfo=timezone.utc)
IMPORTED_AT = DECIDED_AT + timedelta(days=2)
QUERY = {"month": "2026-08", "feeDirection": "PROMOTION", "metricScope": "MONTH", "q": "store-1"}


def _seed_and_correct(client, db_session, monkeypatch):
    _login(client)
    db_session.add_all([
        StoreFinanceProfile(profile_id="original-profile", store_id="store-1", profile_type=1,
            source_type=1, version_no=1, is_current=True, store_name_snapshot="Store One", sap_code="OLD"),
        SapSuggestion(suggestion_id="older-suggestion", store_id="store-1", suggested_sap_code="OLD",
            suggestion_note="synthetic", submitted_by="synthetic", submitted_at=DECIDED_AT - timedelta(days=1)),
    ])
    db_session.commit()
    monkeypatch.setattr(dashboard_routes, "utcnow", lambda: DECIDED_AT)
    corrected = client.post("/api/v1/admin/finance/stores/store-1/sap-corrections",
        json={"readVersion": 1, "finalSapCode": "NEW", "changeReason": "synthetic correction"},
        headers={"Idempotency-Key": uuid4().hex})
    assert corrected.status_code == 200, corrected.text
    assert _listed(client)["sapStatus"] == "CONFIRMED"
    current = db_session.scalar(select(StoreFinanceProfile).where(StoreFinanceProfile.is_current.is_(True)))
    assert current.source_type == 3 and current.factory_confirmed is None and current.confirmed_at is None
    audit = db_session.scalar(select(FinanceOperationAudit).where(FinanceOperationAudit.operation_type == "SAP_SINGLE_CORRECTION"))
    assert audit.target_id == current.profile_id
    monkeypatch.setattr(dashboard_routes, "utcnow", lambda: IMPORTED_AT)
    return current.profile_id, audit.audit_id


def _listed(client):
    response = client.get("/api/v1/admin/finance/stores", params=QUERY)
    assert response.status_code == 200, response.text
    return response.json()["data"]["list"][0]


def _import_basic(client, sap="NEW", *, imported_at=IMPORTED_AT):
    headers = "storeId,storeName,importedAt" if sap is None else "storeId,storeName,sapCode,importedAt"
    values = f"store-1,Store One,{imported_at.isoformat()}" if sap is None else f"store-1,Store One,{sap},{imported_at.isoformat()}"
    uploaded = _upload(client, "BASIC_INFO", headers + "\n" + values + "\n")
    assert uploaded.status_code == 200, uploaded.text
    batch = uploaded.json()["data"]
    path = "corrections" if batch["scenario"] == "DIFF_CONFIRMATION_REQUIRED" else "commits"
    result = client.post(f"/api/v1/admin/finance-imports/{batch['batchId']}/{path}",
        json={"readVersion": batch["readVersion"], "changeReason": "synthetic metadata import"},
        headers={"Idempotency-Key": uuid4().hex})
    assert result.status_code == 200, result.text
    return result.json()["data"]


def _reverse(client, committed):
    response = client.post(f"/api/v1/admin/finance-imports/{committed['batchId']}/reversals",
        json={"readVersion": committed["currentVersion"], "changeReason": "synthetic restore"},
        headers={"Idempotency-Key": uuid4().hex})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _assert_formal_readback(client, db_session, original_profile_id, original_audit_id, *, expected="CONFIRMED"):
    with Session(db_session.get_bind()) as fresh:
        current = fresh.scalar(select(StoreFinanceProfile).where(StoreFinanceProfile.store_id == "store-1", StoreFinanceProfile.profile_type == 1, StoreFinanceProfile.is_current.is_(True)))
        original = fresh.scalar(select(StoreFinanceProfile).where(StoreFinanceProfile.profile_id == original_profile_id))
        audit = fresh.scalar(select(FinanceOperationAudit).where(FinanceOperationAudit.audit_id == original_audit_id))
        assert current.sap_code == "NEW" and current.profile_id != original_profile_id
        assert current.factory_confirmed is None and current.confirmed_at is None
        assert original.factory_confirmed is None and original.confirmed_at is None
        assert audit.target_id == original_profile_id and audit.occurred_at.replace(tzinfo=timezone.utc) == DECIDED_AT
        assert fresh.scalar(select(func.count()).select_from(FinanceOperationAudit).where(FinanceOperationAudit.operation_type == "SAP_SINGLE_CORRECTION")) == 1
    assert _listed(client)["sapStatus"] == expected
    export = client.get("/api/v1/admin/finance/stores/export", params=QUERY)
    assert export.status_code == 200
    rows = list(csv.DictReader(StringIO(export.content.decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["有效SAP编码"] == "NEW"
    discrepancies = client.get("/api/v1/admin/finance/stores/sap-discrepancies/export", params=QUERY)
    assert discrepancies.status_code == 200
    rows = list(csv.DictReader(StringIO(discrepancies.content.decode("utf-8-sig"))))
    assert len(rows) == (0 if expected == "CONFIRMED" else 1)
    if rows:
        assert rows[0]["sap_status"] == expected


@pytest.mark.parametrize("sap", ["NEW", "", None], ids=["same-value", "blank", "missing"])
def test_single_correction_then_same_basic_import_keeps_exact_resolution_not_factory_confirmation(client, db_session, monkeypatch, sap):
    source_profile, source_audit = _seed_and_correct(client, db_session, monkeypatch)
    _import_basic(client, sap)
    _assert_formal_readback(client, db_session, source_profile, source_audit)
    _import_basic(client, "NEW", imported_at=IMPORTED_AT + timedelta(hours=1))
    _assert_formal_readback(client, db_session, source_profile, source_audit)


@pytest.mark.parametrize("changed_sap", ["NEW", "NEW2"], ids=["reverse-same-value", "reverse-real-change"])
def test_formal_reversal_restores_precise_previous_resolution_source(client, db_session, monkeypatch, changed_sap):
    source_profile, source_audit = _seed_and_correct(client, db_session, monkeypatch)
    committed = _import_basic(client, changed_sap)
    if changed_sap == "NEW2":
        assert _listed(client)["sapStatus"] == "FINANCE_ACTION_REQUIRED"
    reversed_batch = _reverse(client, committed)
    row = db_session.scalar(select(FinanceImportRow).where(FinanceImportRow.batch_id == reversed_batch["batchId"]))
    assert row.previous_target_record_id == source_profile
    _assert_formal_readback(client, db_session, source_profile, source_audit)


def test_plain_change_back_to_historical_same_code_does_not_guess_old_resolution(client, db_session, monkeypatch):
    _seed_and_correct(client, db_session, monkeypatch)
    _import_basic(client, "NEW2")
    assert _listed(client)["sapStatus"] == "FINANCE_ACTION_REQUIRED"
    _import_basic(client, "NEW", imported_at=IMPORTED_AT + timedelta(hours=1))
    assert _listed(client)["effectiveSapCode"] == "NEW"
    assert _listed(client)["sapStatus"] == "FINANCE_ACTION_REQUIRED"


@pytest.mark.parametrize("restore", [False, True], ids=["same-import", "reversal"])
def test_newer_suggestion_is_not_swallowed_by_later_metadata_or_restoration_time(client, db_session, monkeypatch, restore):
    source_profile, source_audit = _seed_and_correct(client, db_session, monkeypatch)
    suggestion = db_session.scalar(select(SapSuggestion).where(SapSuggestion.suggestion_id == "older-suggestion"))
    suggestion.is_current = False
    db_session.add(SapSuggestion(suggestion_id="newer-suggestion", store_id="store-1", version_no=2,
        suggested_sap_code="AFTER-DECISION", suggestion_note="new synthetic objection", submitted_by="synthetic",
        submitted_at=DECIDED_AT + timedelta(days=1)))
    db_session.commit()
    assert _listed(client)["sapStatus"] == "FINANCE_ACTION_REQUIRED"
    committed = _import_basic(client, "NEW2" if restore else "NEW")
    if restore:
        _reverse(client, committed)
    _assert_formal_readback(client, db_session, source_profile, source_audit, expected="FINANCE_ACTION_REQUIRED")


def test_cross_store_import_pointer_is_not_resolution_proof(client, db_session, monkeypatch):
    _seed_and_correct(client, db_session, monkeypatch)
    committed = _import_basic(client)
    other = StoreFinanceProfile(profile_id="other-store-source", store_id="store-2", profile_type=1,
        source_type=3, version_no=1, is_current=True, store_name_snapshot="Store Two", sap_code="NEW")
    db_session.add(other)
    row = db_session.scalar(select(FinanceImportRow).where(FinanceImportRow.batch_id == committed["batchId"]))
    row.normalized_payload = {**row.normalized_payload, "_previewProfileId": other.profile_id}
    db_session.commit()
    assert _listed(client)["sapStatus"] == "FINANCE_ACTION_REQUIRED"


@pytest.mark.parametrize("restore", [False, True], ids=["same-basic-after-factory-confirmation", "restore-factory-confirmation"])
def test_historical_profile_modified_time_is_not_a_new_factory_resolution(client, db_session, monkeypatch, restore):
    _seed_and_correct(client, db_session, monkeypatch)
    confirmed_at = DECIDED_AT + timedelta(hours=1)
    monkeypatch.setattr(dashboard_routes, "utcnow", lambda: confirmed_at)
    uploaded = _upload(client, "SAP_CONFIRMATION",
        "storeId,storeName,financeInitialSap,serviceStoreCode,finalSapCode,factoryConfirmationResult,confirmedAt\n"
        f"store-1,Store One,OLD,SVC-001,NEW,CONFIRMED,{confirmed_at.isoformat()}\n")
    batch = uploaded.json()["data"]
    response = client.post(f"/api/v1/admin/finance-imports/{batch['batchId']}/commits",
        json={"readVersion": batch["readVersion"], "changeReason": "synthetic factory confirmation"},
        headers={"Idempotency-Key": uuid4().hex})
    assert response.status_code == 200, response.text
    assert _listed(client)["sapStatus"] == "CONFIRMED"
    suggestion = db_session.scalar(select(SapSuggestion).where(SapSuggestion.is_current.is_(True)))
    suggestion.is_current = False
    db_session.add(SapSuggestion(suggestion_id="after-factory-confirmation", store_id="store-1", version_no=2,
        suggested_sap_code="LATER-OBJECTION", suggestion_note="new synthetic objection", submitted_by="synthetic",
        submitted_at=DECIDED_AT + timedelta(days=1)))
    db_session.commit()
    assert _listed(client)["sapStatus"] == "FINANCE_ACTION_REQUIRED"
    monkeypatch.setattr(dashboard_routes, "utcnow", lambda: IMPORTED_AT)
    committed = _import_basic(client, "NEW2" if restore else "NEW")
    if restore:
        _reverse(client, committed)
    # Deactivating the original profile updates its gmt_modified. That metadata
    # timestamp must never replace the actual earlier decision/batch timestamp.
    assert _listed(client)["sapStatus"] == "FINANCE_ACTION_REQUIRED"
    with Session(db_session.get_bind()) as fresh:
        current = fresh.scalar(select(StoreFinanceProfile).where(StoreFinanceProfile.store_id == "store-1", StoreFinanceProfile.profile_type == 1, StoreFinanceProfile.is_current.is_(True)))
        assert current.sap_code == "NEW" and current.factory_confirmed is True
        assert current.confirmed_at.replace(tzinfo=timezone.utc) == confirmed_at
