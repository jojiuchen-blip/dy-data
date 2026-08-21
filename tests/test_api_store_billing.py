from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.auth import AuthContext, get_current_user  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    DimStore,
    SettlementStatement,
    SettlementStatementConfirmation,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    _seed_statements(db_session)
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _seed_statements(db_session: Session) -> None:
    db_session.add_all(
        [
            DimStore(store_id="store-1", store_name="Store One", is_active=True),
            DimStore(store_id="store-2", store_name="Store Two", is_active=True),
            SettlementStatement(
                statement_id="statement-1-v1",
                store_id="store-1",
                statement_month="2026-08",
                version_no=1,
                is_current=False,
                statement_status=4,
                promotion_original_fee_cent=1000,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=1000,
                management_original_fee_cent=2000,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=2000,
                created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            ),
            SettlementStatement(
                statement_id="statement-1-v2",
                store_id="store-1",
                statement_month="2026-08",
                version_no=2,
                is_current=True,
                supersedes_statement_id="statement-1-v1",
                statement_status=4,
                promotion_original_fee_cent=1100,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=1100,
                management_original_fee_cent=2200,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=2200,
                created_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            ),
            SettlementStatement(
                statement_id="statement-2-v1",
                store_id="store-2",
                statement_month="2026-08",
                version_no=1,
                is_current=True,
                statement_status=4,
                promotion_original_fee_cent=900,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=900,
                management_original_fee_cent=800,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=800,
            ),
            SettlementStatement(
                statement_id="statement-1-sep-v1",
                store_id="store-1",
                statement_month="2026-09",
                version_no=1,
                is_current=True,
                statement_status=4,
                promotion_original_fee_cent=1300,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=1300,
                management_original_fee_cent=0,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=0,
            ),
        ]
    )
    db_session.commit()


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert response.status_code == 200


def test_store_settlement_reads_current_list_and_version_history(client: TestClient) -> None:
    _login(client)

    listed = client.get(
        "/api/v1/store-settlements",
        params={"storeId": "store-1", "month": "2026-08", "metricScope": "MONTH"},
    )
    assert listed.status_code == 200
    row = listed.json()["data"]["list"][0]
    assert row["statementId"] == "statement-1-v2"
    assert row["versionNo"] == 2
    assert row["isCurrent"] is True
    assert row["supersedesStatementId"] == "statement-1-v1"
    assert row["promotionAmountCent"] == 1100
    assert row["managementAmountCent"] == 2200
    assert listed.json()["data"]["metrics"]["month"] == {
        "promotionAmountCent": 1100,
        "managementAmountCent": 2200,
    }

    cumulative = client.get(
        "/api/v1/store-settlements",
        params={
            "storeId": "store-1",
            "month": "2026-08",
            "metricScope": "CUMULATIVE",
        },
    )
    assert cumulative.status_code == 200
    assert cumulative.json()["data"]["metrics"]["cumulative"] == {
        "promotionAmountCent": 1100,
        "managementAmountCent": 2200,
    }

    detail = client.get("/api/v1/store-settlements/statement-1-v1")
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["isCurrent"] is False
    assert [version["statementId"] for version in detail_data["versions"]] == [
        "statement-1-v2",
        "statement-1-v1",
    ]


def test_store_confirmation_rechecks_current_version_and_replays_idempotently(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    body = {
        "feeDirection": "PROMOTION",
        "confirmedAmountCent": 1100,
        "readVersion": 2,
    }
    headers = {"Idempotency-Key": "store-confirmation-key-0001"}

    first = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json=body,
        headers=headers,
    )
    second = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json=body,
        headers=headers,
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert first.json()["data"]["status"] == "CONFIRMED"
    assert first.json()["data"]["confirmedAmountCent"] == 1100
    assert first.json()["data"]["versionNo"] == 2
    assert db_session.scalar(
        select(SettlementStatementConfirmation).where(
            SettlementStatementConfirmation.statement_id == "statement-1-v2"
        )
    ) is not None

    stale = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json={**body, "readVersion": 1},
        headers={"Idempotency-Key": "store-confirmation-key-0002"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "STATEMENT_VERSION_CONFLICT"


def test_store_settlement_rejects_store_outside_account_scope(
    client: TestClient,
) -> None:
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="store-user",
        username="store-user",
        display_name="Store User",
        role="store",
        store_ids=("store-1",),
        auth_type="user",
        store_scope_mode="assigned",
    )

    response = client.get(
        "/api/v1/store-settlements",
        params={"storeId": "store-2", "month": "2026-08", "metricScope": "MONTH"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "DATA_SCOPE_FORBIDDEN"


def test_promotion_invoice_registers_multiple_complete_period_allocations(
    client: TestClient,
) -> None:
    _login(client)
    for statement_id, amount, version, key in (
        ("statement-1-v2", 1100, 2, "promotion-confirmation-key-01"),
        ("statement-1-sep-v1", 1300, 1, "promotion-confirmation-key-02"),
    ):
        response = client.post(
            f"/api/v1/store-settlements/{statement_id}/confirmations",
            json={
                "feeDirection": "PROMOTION",
                "confirmedAmountCent": amount,
                "readVersion": version,
            },
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 200

    registered = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "invoiceNumber": "12345678901234567890",
            "invoiceDate": "2026-10-05",
            "invoiceAmountCent": 2400,
            "allocations": [
                {
                    "statementId": "statement-1-v2",
                    "statementMonth": "2026-08",
                    "allocatedAmountCent": 1100,
                    "readVersion": 2,
                },
                {
                    "statementId": "statement-1-sep-v1",
                    "statementMonth": "2026-09",
                    "allocatedAmountCent": 1300,
                    "readVersion": 1,
                },
            ],
        },
        headers={"Idempotency-Key": "promotion-invoice-register-0001"},
    )
    assert registered.status_code == 200
    assert registered.json()["data"]["status"] == "SUBMITTED_PENDING_FACTORY_REVIEW"
    assert len(registered.json()["data"]["allocations"]) == 2

    listed = client.get(
        "/api/v1/promotion-invoices",
        params={"storeId": "store-1", "month": "2026-08"},
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["list"][0]["invoiceNumber"] == "12345678901234567890"
