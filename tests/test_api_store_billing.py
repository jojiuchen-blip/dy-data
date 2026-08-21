from __future__ import annotations

import sys
from datetime import date, datetime, timezone
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
    InvoiceRecord,
    PromotionInvoice,
    PromotionInvoiceAllocation,
    SettlementStatement,
    SettlementStatementConfirmation,
    SettlementStatementEntry,
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


def test_rejected_promotion_invoice_replaces_current_period_allocations(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    allocations = [
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
    ]
    for statement_id, amount, version, key in (
        ("statement-1-v2", 1100, 2, "reupload-confirmation-key-01"),
        ("statement-1-sep-v1", 1300, 1, "reupload-confirmation-key-02"),
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

    first = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "invoiceNumber": "12345678901234567890",
            "invoiceDate": "2026-10-05",
            "invoiceAmountCent": 2400,
            "allocations": allocations,
        },
        headers={"Idempotency-Key": "reupload-invoice-register-0001"},
    )
    assert first.status_code == 200
    previous = db_session.scalar(select(PromotionInvoice))
    assert previous is not None
    previous.invoice_status = 4
    db_session.commit()

    replacement = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "invoiceNumber": "09876543210987654321",
            "invoiceDate": "2026-10-06",
            "invoiceAmountCent": 2400,
            "allocations": allocations,
        },
        headers={"Idempotency-Key": "reupload-invoice-register-0002"},
    )

    assert replacement.status_code == 200
    assert replacement.json()["data"]["versionNo"] == 2
    assert replacement.json()["data"]["supersedesInvoiceId"] == previous.invoice_id
    db_session.expire_all()
    assert db_session.scalar(
        select(PromotionInvoice.is_current).where(
            PromotionInvoice.invoice_id == previous.invoice_id
        )
    ) is False


def test_admin_finance_summary_reads_current_monthly_fee_facts(
    client: TestClient,
) -> None:
    _login(client)

    response = client.get(
        "/api/v1/admin/finance/summary",
        params={
            "month": "2026-08",
            "storeId": "store-1",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["feeDirection"] == "PROMOTION"
    assert data["metrics"]["statementTotalCent"] == 1100
    assert data["metrics"]["confirmedAmountCent"] == 0
    assert data["metrics"]["issuedAmountCent"] == 0


def test_admin_finance_queries_read_current_invoices_orders_and_stores(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    _seed_finance_query_facts(db_session)

    promotion_invoices = client.get(
        "/api/v1/admin/finance/invoices",
        params={"month": "2026-08", "feeDirection": "PROMOTION"},
    )
    assert promotion_invoices.status_code == 200
    promotion_row = promotion_invoices.json()["data"]["list"][0]
    assert promotion_row["invoiceId"] == "promotion-invoice-current"
    assert promotion_row["allocatedAmountCent"] == 1100
    assert promotion_row["status"] == "APPROVED_SETTLED"

    management_invoices = client.get(
        "/api/v1/admin/finance/invoices",
        params={"month": "2026-08", "feeDirection": "MANAGEMENT"},
    )
    assert management_invoices.status_code == 200
    management_row = management_invoices.json()["data"]["list"][0]
    assert management_row["invoiceId"] == "management-invoice-current"
    assert management_row["invoiceAmountCent"] == 2200
    assert management_row["settledAt"] == "2026-10-05T00:00:00+00:00"

    orders = client.get(
        "/api/v1/admin/finance/order-details",
        params={"month": "2026-08", "feeDirection": "PROMOTION"},
    )
    assert orders.status_code == 200
    assert orders.json()["data"]["list"] == [
        {
            "statementEntryId": "entry-promotion-current",
            "statementId": "statement-1-v2",
            "storeId": "store-1",
            "statementMonth": "2026-08",
            "feeDirection": "PROMOTION",
            "orderId": "order-promotion-current",
            "couponId": "coupon-promotion-current",
            "originalBusinessMonth": "2026-08",
            "statementPostingMonth": "2026-08",
            "baseAmountCent": 11000,
            "feeAmountCent": 1100,
        }
    ]

    stores = client.get(
        "/api/v1/admin/finance/stores",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )
    assert stores.status_code == 200
    store_row = stores.json()["data"]["list"][0]
    assert store_row["storeId"] == "store-1"
    assert store_row["statementTotalCent"] == 1100
    assert store_row["issuedAmountCent"] == 1100


def test_admin_finance_summary_keeps_confirmations_monthly_and_pending_nonnegative(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    _seed_finance_query_facts(db_session)
    db_session.add_all(
        [
            SettlementStatementConfirmation(
                confirmation_id="confirmation-promotion-aug",
                statement_id="statement-1-v2",
                fee_direction=1,
                confirmation_status=1,
                confirmed_amount_cent=1100,
                confirmed_by="store-1",
            ),
            SettlementStatementConfirmation(
                confirmation_id="confirmation-promotion-sep",
                statement_id="statement-1-sep-v1",
                fee_direction=1,
                confirmation_status=1,
                confirmed_amount_cent=1300,
                confirmed_by="store-1",
            ),
            SettlementStatement(
                statement_id="statement-1-oct-v1",
                store_id="store-1",
                statement_month="2026-10",
                version_no=1,
                is_current=True,
                statement_status=4,
                promotion_original_fee_cent=0,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=0,
                management_original_fee_cent=-100,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=-100,
            ),
        ]
    )
    db_session.flush()
    db_session.add(
        SettlementStatementConfirmation(
            confirmation_id="confirmation-management-oct",
            statement_id="statement-1-oct-v1",
            fee_direction=2,
            confirmation_status=1,
            confirmed_amount_cent=-100,
            confirmed_by="store-1",
        )
    )
    db_session.commit()

    cumulative = client.get(
        "/api/v1/admin/finance/summary",
        params={
            "month": "2026-09",
            "storeId": "store-1",
            "feeDirection": "PROMOTION",
            "metricScope": "CUMULATIVE",
        },
    )
    assert cumulative.status_code == 200
    assert cumulative.json()["data"]["metrics"] == {
        "statementTotalCent": 2400,
        "confirmedAmountCent": 1300,
        "pendingInvoiceAmountCent": 1300,
        "issuedAmountCent": 1100,
        "settledOrDeductedAmountCent": 1100,
    }

    negative = client.get(
        "/api/v1/admin/finance/summary",
        params={
            "month": "2026-10",
            "storeId": "store-1",
            "feeDirection": "MANAGEMENT",
            "metricScope": "MONTH",
        },
    )
    assert negative.status_code == 200
    assert negative.json()["data"]["metrics"]["pendingInvoiceAmountCent"] == 0


def test_admin_finance_queries_reject_store_role(client: TestClient) -> None:
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="admin-user",
        username="admin-user",
        display_name="Admin User",
        role="admin",
        store_ids=(),
        auth_type="user",
        store_scope_mode="all",
    )
    admin_response = client.get(
        "/api/v1/admin/finance/summary",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )
    assert admin_response.status_code == 200

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
        "/api/v1/admin/finance/summary",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "DATA_SCOPE_FORBIDDEN"


def _seed_finance_query_facts(db_session: Session) -> None:
    settled_at = datetime(2026, 10, 5, tzinfo=timezone.utc)
    db_session.add_all(
        [
            PromotionInvoice(
                invoice_id="promotion-invoice-current",
                store_id="store-1",
                version_no=2,
                is_current=True,
                supersedes_invoice_id="promotion-invoice-old",
                invoice_number="12345678901234567890",
                invoice_date=date(2026, 10, 5),
                invoice_amount_cent=1100,
                invoice_status=3,
                registered_by="system-admin",
                registered_at=settled_at,
            ),
            PromotionInvoiceAllocation(
                allocation_id="promotion-allocation-current",
                invoice_id="promotion-invoice-current",
                store_id="store-1",
                statement_id="statement-1-v2",
                statement_month="2026-08",
                allocated_amount_cent=1100,
                is_current=True,
            ),
            InvoiceRecord(
                invoice_id="management-invoice-current",
                store_id="store-1",
                statement_month="2026-08",
                statement_id="statement-1-v2",
                fee_direction=2,
                version_no=1,
                is_current=True,
                invoice_number="12345678901234567891",
                invoice_date=date(2026, 10, 5),
                invoice_amount_cent=2200,
                invoice_status=3,
                source_type=2,
                registered_by="system-admin",
                registered_at=settled_at,
            ),
            SettlementStatementEntry(
                statement_entry_id="entry-promotion-current",
                statement_id="statement-1-v2",
                statement_line_id="line-promotion-current",
                source_type=1,
                source_record_id="source-promotion-current",
                original_fee_result_id="fee-result-promotion-current",
                coupon_id="coupon-promotion-current",
                order_id="order-promotion-current",
                fee_direction=1,
                original_business_month="2026-08",
                statement_posting_month="2026-08",
                base_amount_cent=11000,
                fee_amount_cent=1100,
                rule_version="rule-v1",
            ),
            SettlementStatementEntry(
                statement_entry_id="entry-management-current",
                statement_id="statement-1-v2",
                statement_line_id="line-management-current",
                source_type=1,
                source_record_id="source-management-current",
                original_fee_result_id="fee-result-management-current",
                coupon_id="coupon-management-current",
                order_id="order-management-current",
                fee_direction=2,
                original_business_month="2026-08",
                statement_posting_month="2026-08",
                base_amount_cent=11000,
                fee_amount_cent=2200,
                rule_version="rule-v1",
            ),
        ]
    )
    db_session.commit()
