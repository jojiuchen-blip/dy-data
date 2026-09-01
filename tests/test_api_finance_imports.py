from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    DimStore,
    FinanceImportBatch,
    FinanceImportRow,
    InvoiceRecord,
    InvoiceStatusEvent,
    PromotionInvoice,
    PromotionInvoiceAllocation,
    PromotionInvoiceNumberRegistry,
    SettlementStatement,
    SettlementStatementConfirmation,
    StoreFinanceProfile,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    db_session.add_all(
        [
            DimStore(store_id="store-1", store_name="Store One", is_active=True),
            DimStore(store_id="store-2", store_name="Store Two", is_active=True),
        ]
    )
    db_session.commit()
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert response.status_code == 200


def _upload(
    client: TestClient, import_type: str, content: str, *, key: str | None = None
):
    return client.post(
        "/api/v1/admin/finance-imports",
        data={"importType": import_type, "statementMonth": "2026-08"},
        files={"file": (f"{import_type.lower()}.csv", content.encode("utf-8"), "text/csv")},
        headers={"Idempotency-Key": key or f"finance-upload-{uuid4().hex}"},
    )


def _commit(client: TestClient, batch: dict, key: str):
    return client.post(
        f"/api/v1/admin/finance-imports/{batch['batchId']}/commits",
        json={"readVersion": batch["readVersion"], "changeReason": "测试导入"},
        headers={"Idempotency-Key": key},
    )


def test_basic_info_import_prevalidates_commits_replays_and_versions(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    content = (
        "storeId,storeName,sapCode,importedAt\n"
        "store-1,Store One,SAP-001,2026-08-21T10:00:00+08:00\n"
        "store-2,Store Two,SAP-002,2026-08-21T10:00:00+08:00\n"
    )
    uploaded = _upload(
        client, "BASIC_INFO", content, key="finance-basic-upload-0001"
    )
    assert uploaded.status_code == 200
    batch = uploaded.json()["data"]
    assert batch["scenario"] == "FIRST_IMPORT_READY"
    assert batch["totalRows"] == 2
    assert db_session.scalar(select(func.count()).select_from(StoreFinanceProfile)) == 0
    upload_replay = _upload(
        client, "BASIC_INFO", content, key="finance-basic-upload-0001"
    )
    assert upload_replay.status_code == 200
    assert upload_replay.json()["data"] == uploaded.json()["data"]
    assert db_session.scalar(select(func.count()).select_from(FinanceImportBatch)) == 1

    detail = client.get(f"/api/v1/admin/finance-imports/{batch['batchId']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["errors"]["list"] == []

    committed = client.post(
        f"/api/v1/admin/finance-imports/{batch['batchId']}/commits",
        json={"readVersion": batch["readVersion"], "changeReason": "首次导入"},
        headers={"Idempotency-Key": "finance-basic-commit-0001"},
    )
    assert committed.status_code == 200
    assert committed.json()["data"]["status"] == "COMMITTED"
    assert db_session.scalar(select(func.count()).select_from(StoreFinanceProfile)) == 2

    replay = client.post(
        f"/api/v1/admin/finance-imports/{batch['batchId']}/commits",
        json={"readVersion": batch["readVersion"], "changeReason": "首次导入"},
        headers={"Idempotency-Key": "finance-basic-commit-0001"},
    )
    assert replay.status_code == 200
    assert db_session.scalar(select(func.count()).select_from(StoreFinanceProfile)) == 2

    unchanged = _upload(client, "BASIC_INFO", content)
    assert unchanged.status_code == 200
    assert unchanged.json()["data"]["scenario"] == "NO_CHANGE"

    changed = _upload(
        client,
        "BASIC_INFO",
        content.replace("SAP-001", "SAP-001-NEW"),
    )
    changed_batch = changed.json()["data"]
    assert changed_batch["scenario"] == "DIFF_CONFIRMATION_REQUIRED"
    corrected = client.post(
        f"/api/v1/admin/finance-imports/{changed_batch['batchId']}/corrections",
        json={"readVersion": changed_batch["readVersion"], "changeReason": "更正 SAP"},
        headers={"Idempotency-Key": "finance-basic-correct-0001"},
    )
    assert corrected.status_code == 200
    profiles = list(
        db_session.scalars(
            select(StoreFinanceProfile)
            .where(StoreFinanceProfile.store_id == "store-1")
            .order_by(StoreFinanceProfile.version_no)
        )
    )
    assert [profile.version_no for profile in profiles] == [1, 2]
    assert [profile.is_current for profile in profiles] == [False, True]
    assert profiles[-1].sap_code == "SAP-001-NEW"


def test_import_collects_all_errors_and_downloads_csv_without_business_writes(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    response = _upload(
        client,
        "BASIC_INFO",
        "storeId,storeName,sapCode,importedAt\n"
        ",,SAP-X,not-a-date\n"
        "missing-store,Wrong Name,,2026-08-21T10:00:00+08:00\n",
    )
    assert response.status_code == 200
    batch = response.json()["data"]
    assert batch["scenario"] == "BATCH_VALIDATION_FAILED"
    assert batch["errorRows"] == 2
    assert db_session.scalar(select(func.count()).select_from(StoreFinanceProfile)) == 0
    assert db_session.scalar(select(func.count()).select_from(FinanceImportRow)) == 2

    detail = client.get(
        f"/api/v1/admin/finance-imports/{batch['batchId']}",
        params={"errorPage": 1, "errorPageSize": 1},
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["errors"]["total"] == 4
    assert len(detail.json()["data"]["errors"]["list"]) == 2

    downloaded = client.get(
        f"/api/v1/admin/finance-imports/{batch['batchId']}/error-file"
    )
    assert downloaded.status_code == 200
    text = downloaded.content.decode("utf-8-sig")
    assert "rowNumber,businessKey,field,originalValue,reason,suggestion" in text
    assert "missing-store" in text
    assert db_session.scalar(select(func.count()).select_from(FinanceImportBatch)) == 1


def test_sap_confirmation_import_appends_profile_history(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    uploaded = _upload(
        client,
        "SAP_CONFIRMATION",
        "storeId,storeName,financeInitialSap,serviceStoreCode,finalSapCode,factoryConfirmationResult,confirmedAt\n"
        "store-1,Store One,SAP-OLD,SVC-001,SAP-FINAL,CONFIRMED,2026-08-21T11:00:00+08:00\n",
    )
    assert uploaded.status_code == 200
    batch = uploaded.json()["data"]
    committed = _commit(client, batch, "finance-sap-commit-0001")
    assert committed.status_code == 200
    profile = db_session.scalar(
        select(StoreFinanceProfile).where(StoreFinanceProfile.profile_type == 1)
    )
    assert profile is not None
    assert profile.sap_code == "SAP-FINAL"
    assert profile.initial_sap_code == "SAP-OLD"
    assert profile.service_store_code == "SVC-001"
    assert profile.factory_confirmed is True


def test_promotion_factory_result_versions_invoice_and_persists_result(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    db_session.add_all(
        [
            SettlementStatement(
                statement_id="statement-promotion",
                store_id="store-1",
                statement_month="2026-08",
                version_no=1,
                is_current=True,
                statement_status=4,
                promotion_original_fee_cent=1200,
                promotion_net_fee_cent=1200,
            ),
                PromotionInvoice(
                    invoice_id="promotion-invoice-v1",
                    physical_invoice_id="physical-promotion-invoice-v1",
                store_id="store-1",
                version_no=1,
                is_current=True,
                invoice_number="12345678901234567890",
                invoice_date=date(2026, 8, 20),
                invoice_amount_cent=1200,
                buyer_name="比亚迪汽车销售有限公司",
                tax_rate_percent=6,
                invoice_status=2,
                    registered_by="store-1",
                ),
                PromotionInvoiceNumberRegistry(
                    invoice_number="12345678901234567890",
                    physical_invoice_id="physical-promotion-invoice-v1",
                    first_invoice_id="promotion-invoice-v1",
                    store_id="store-1",
                ),
            PromotionInvoiceAllocation(
                allocation_id="promotion-allocation-v1",
                invoice_id="promotion-invoice-v1",
                store_id="store-1",
                statement_id="statement-promotion",
                statement_month="2026-08",
                settlement_batch_month="2026-08",
                allocated_amount_cent=1200,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    uploaded = _upload(
        client,
        "PROMOTION_FACTORY_RESULT",
        "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n"
        "12345678901234567890,APPROVED_SETTLED,,2026-08-21,1200\n",
    )
    assert uploaded.status_code == 200
    batch = uploaded.json()["data"]
    assert batch["scenario"] == "FIRST_IMPORT_READY"
    committed = _commit(client, batch, "finance-promotion-commit-0001")
    assert committed.status_code == 200
    current = db_session.scalar(
        select(PromotionInvoice).where(PromotionInvoice.is_current.is_(True))
    )
    event = db_session.scalar(select(InvoiceStatusEvent))
    assert current is not None and current.version_no == 2 and current.invoice_status == 3
    assert event is not None
    assert event.business_date == date(2026, 8, 21)
    assert event.business_amount_cent == 1200
    statement = client.get(
        "/api/v1/store-settlements",
        params={
            "storeId": "store-1",
            "month": "2026-08",
            "metricScope": "MONTH",
            "feeDirection": "PROMOTION",
        },
    )
    assert statement.status_code == 200
    assert (
        statement.json()["data"]["list"][0]["promotionInvoiceStatus"]
        == "APPROVED_SETTLED"
    )


def test_management_factory_result_is_atomic_full_amount_and_versioned(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    db_session.add(
        SettlementStatement(
            statement_id="statement-management",
            store_id="store-1",
            statement_month="2026-08",
            version_no=1,
            is_current=True,
            statement_status=4,
            management_original_fee_cent=2500,
            management_net_fee_cent=2500,
        )
    )
    db_session.flush()
    db_session.add(
        SettlementStatementConfirmation(
            confirmation_id="confirmation-management",
            statement_id="statement-management",
            fee_direction=2,
            confirmation_status=1,
            confirmed_amount_cent=2500,
            confirmed_by="store-1",
        )
    )
    db_session.commit()

    uploaded = _upload(
        client,
        "MANAGEMENT_FACTORY_RESULT",
        "storeId,statementMonth,storeName,invoiceNumber,invoiceDate,deductionDate,deductionAmountCent\n"
        "store-1,2026-08,Store One,22345678901234567890,2026-08-20,2026-08-21,2500\n",
    )
    assert uploaded.status_code == 200
    batch = uploaded.json()["data"]
    committed = _commit(client, batch, "finance-management-commit-0001")
    assert committed.status_code == 200
    invoice = db_session.scalar(
        select(InvoiceRecord).where(InvoiceRecord.is_current.is_(True))
    )
    assert invoice is not None
    assert invoice.invoice_amount_cent == 2500
    assert invoice.factory_deduction_date == date(2026, 8, 21)
    assert invoice.factory_deduction_amount_cent == 2500
