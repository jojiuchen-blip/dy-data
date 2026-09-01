from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.auth import AuthContext, get_current_user  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from dy_api.routes import dashboard as dashboard_routes  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    DimStore,
    FinanceImportBatch,
    FinanceImportRow,
    FinanceOperationAudit,
    InvoiceRecord,
    InvoiceStatusEvent,
    PromotionInvoice,
    PromotionInvoiceAllocation,
    PromotionInvoiceLifecycleEvent,
    PromotionInvoiceNumberRegistry,
    PromotionInvoiceReplacementSource,
    SettlementCarryforwardApplication,
    SettlementCarryforwardSource,
    SettlementDispute,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementStatement,
    SettlementStatementConfirmation,
    SettlementStatementEntry,
    SettlementStatementLine,
    DimSkuProductRule,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    RawDouyinVerifyRecord,
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
                store_name_snapshot="Store One Historical",
                sap_code_snapshot="SAP-STORE-ONE-HIST",
                store_snapshot_status="LIVE_CAPTURED",
                store_snapshot_profile_id="profile-store-one-hist",
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


def _act_as_store(client: TestClient, store_id: str = "store-1") -> None:
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=f"{store_id}-user",
        username=f"{store_id}-user",
        display_name=f"{store_id} User",
        role="store",
        store_ids=(store_id,),
        auth_type="user",
        store_scope_mode="assigned",
    )


def _manual_invoice_fields(invoice_amount_cent: int) -> dict[str, object]:
    tax_amount_cent = int(
        (Decimal(invoice_amount_cent) * Decimal(6) / Decimal(106)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )
    return {
        "fillerPhone": "13812345678",
        "netAmountCent": invoice_amount_cent - tax_amount_cent,
        "taxAmountCent": tax_amount_cent,
    }


def _seed_current_promotion_invoice(
    db_session: Session,
    *,
    invoice_id: str,
    physical_invoice_id: str,
    invoice_number: str,
    store_id: str = "store-1",
    invoice_status: int = 2,
) -> None:
    db_session.add_all(
        [
            PromotionInvoice(
                invoice_id=invoice_id,
                physical_invoice_id=physical_invoice_id,
                store_id=store_id,
                version_no=1,
                version_kind=1,
                is_current=True,
                invoice_number=invoice_number,
                invoice_date=date(2026, 8, 10),
                invoice_amount_cent=1100,
                buyer_name="比亚迪汽车销售有限公司",
                tax_rate_percent=6,
                invoice_status=invoice_status,
                registered_by=f"{store_id}-user",
                registered_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            ),
            PromotionInvoiceNumberRegistry(
                invoice_number=invoice_number,
                physical_invoice_id=physical_invoice_id,
                first_invoice_id=invoice_id,
                store_id=store_id,
                registered_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            ),
            PromotionInvoiceAllocation(
                allocation_id=f"allocation-{invoice_id}",
                invoice_id=invoice_id,
                store_id=store_id,
                statement_id=(
                    "statement-1-v2" if store_id == "store-1" else "statement-2-v1"
                ),
                statement_month="2026-08",
                settlement_batch_month="2026-07",
                allocated_amount_cent=1100 if store_id == "store-1" else 900,
                is_current=True,
            ),
        ]
    )
    db_session.commit()


def test_store_invoice_status_uses_exact_cross_period_search_and_combined_metrics(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    _act_as_store(client)
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="status-invoice-aug",
        physical_invoice_id="status-physical-aug",
        invoice_number="12345678901234567890",
        invoice_status=2,
    )
    response = client.get(
        "/api/v1/store-invoice-status",
        params={"storeId": "store-1", "month": "2026-09", "invoiceNumber": "12345678901234567890"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["promotionTotal"] == 1
    assert data["promotionInvoices"][0]["invoiceNumber"] == "12345678901234567890"
    assert data["metrics"]["hasData"] is True
    assert "approvedAmountCent" in data["metrics"]
    assert "pendingInvoiceAmountCent" in data["metrics"]
    # The five status cards are the promotion-fee summary; management fee
    # records remain a separate read-only section below.
    assert data["metrics"]["statementTotalCent"] == 2400
    assert data["metrics"]["confirmedAmountCent"] == 0

    partial = client.get(
        "/api/v1/store-invoice-status",
        params={"storeId": "store-1", "invoiceNumber": "1234567890"},
    )
    assert partial.status_code == 200
    assert partial.json()["data"]["promotionTotal"] == 0

    forbidden = client.get(
        "/api/v1/store-invoice-status",
        params={"storeId": "store-2"},
    )
    assert forbidden.status_code == 403


def test_store_invoice_status_validation_uses_the_structured_api_contract(
    client: TestClient,
) -> None:
    _login(client)
    _act_as_store(client)

    response = client.get("/api/v1/store-invoice-status")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_FAILED"


def test_store_invoice_status_excludes_management_pending_rows_from_status_page(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    _act_as_store(client)
    db_session.add(
        InvoiceRecord(
            invoice_id="management-pending-status",
            store_id="store-1",
            statement_month="2026-08",
            statement_id="statement-1-v2",
            fee_direction=2,
            version_no=1,
            is_current=True,
            is_tombstone=False,
            invoice_number="22345678901234567890",
            invoice_date=date(2026, 8, 10),
            invoice_amount_cent=2200,
            invoice_status=1,
            source_type=2,
            registered_by="store-1-user",
            registered_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/store-invoice-status",
        params={"storeId": "store-1", "month": "2026-08"},
    )

    assert response.status_code == 200
    management_rows = response.json()["data"]["managementInvoices"]
    assert management_rows == []


def test_store_invoice_status_exposes_rejection_reason_and_released_amount_as_pending(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    _act_as_store(client)
    db_session.add(
        SettlementStatementConfirmation(
            confirmation_id="confirmation-rejected-status",
            statement_id="statement-1-v2",
            fee_direction=1,
            confirmation_status=1,
            confirmed_amount_cent=1100,
            confirmed_by="store-1-user",
            confirmed_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="status-invoice-rejected",
        physical_invoice_id="status-physical-rejected",
        invoice_number="92345678901234567890",
        invoice_status=4,
    )
    db_session.add(
        InvoiceStatusEvent(
            event_id="status-event-rejected",
            invoice_id="status-invoice-rejected",
            event_type=2,
            from_status=2,
            to_status=4,
            operator_id="factory-import",
            result_reason="税率不正确，请按基准资料重新开具。",
            occurred_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/store-invoice-status",
        params={"storeId": "store-1", "month": "2026-08"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    row = next(
        item
        for item in data["promotionInvoices"]
        if item["invoiceNumber"] == "92345678901234567890"
    )
    assert row["rejectionReason"] == "税率不正确，请按基准资料重新开具。"
    assert data["metrics"]["pendingInvoiceAmountCent"] == 1100


def _seed_confirmed_promotion_periods(
    db_session: Session,
    *,
    store_id: str,
    periods: list[tuple[str, str, int]],
) -> None:
    """Seed current statements with signed promotion confirmations."""

    for statement_id, statement_month, confirmed_amount_cent in periods:
        db_session.add(
            SettlementStatement(
                statement_id=statement_id,
                store_id=store_id,
                statement_month=statement_month,
                version_no=1,
                is_current=True,
                statement_status=4,
                promotion_original_fee_cent=max(confirmed_amount_cent, 0),
                promotion_adjustment_fee_cent=min(confirmed_amount_cent, 0),
                promotion_net_fee_cent=confirmed_amount_cent,
                management_original_fee_cent=0,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=0,
            )
        )
        db_session.add(
            SettlementStatementConfirmation(
                confirmation_id=f"confirmation-{statement_id}",
                statement_id=statement_id,
                fee_direction=1,
                confirmation_status=1,
                confirmed_amount_cent=confirmed_amount_cent,
                confirmed_by="store-user",
                confirmed_at=datetime(2026, 12, 5, tzinfo=timezone.utc),
            )
        )
    db_session.commit()


def _with_current_promotion_group_ids(
    client: TestClient,
    *,
    store_id: str,
    allocations: list[dict],
) -> list[dict]:
    """Attach the server's current deterministic group to allocation fixtures."""

    result: list[dict] = []
    for allocation in allocations:
        response = client.get(
            "/api/v1/store-settlements",
            params={
                "storeId": store_id,
                "month": allocation["statementMonth"],
                "metricScope": "MONTH",
                "feeDirection": "PROMOTION",
                "pageSize": 50,
            },
        )
        assert response.status_code == 200
        statement = next(
            row
            for row in response.json()["data"]["list"]
            if row["statementId"] == allocation["statementId"]
        )
        result.append(
            {
                **allocation,
                "promotionInvoiceGroupId": statement[
                    "promotionInvoiceGroupId"
                ],
            }
        )
    return result


def test_store_settlement_reads_current_list_and_version_history(
    client: TestClient, db_session: Session
) -> None:
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
    assert row["promotionConfirmableAmountCent"] == 1100
    assert row["managementConfirmableAmountCent"] == 2200
    assert listed.json()["data"]["metrics"]["month"] == {
        "promotionAmountCent": 1100,
        "managementAmountCent": 2200,
        "promotionInvoiceableAmountCent": 0,
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
        "promotionInvoiceableAmountCent": 0,
    }

    detail = client.get("/api/v1/store-settlements/statement-1-v1")
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["isCurrent"] is False
    assert [version["statementId"] for version in detail_data["versions"]] == [
        "statement-1-v2",
        "statement-1-v1",
    ]

    db_session.scalar(
        select(DimStore).where(DimStore.store_id == "store-1")
    ).store_name = "Store One Renamed"
    db_session.commit()
    historical_detail = client.get("/api/v1/store-settlements/statement-1-v2")
    assert historical_detail.status_code == 200
    assert historical_detail.json()["data"]["storeName"] == "Store One Historical"


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
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2026, 10, 10, 15, 59, 59, tzinfo=timezone.utc),
    )
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
    _act_as_store(client)
    registered = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "fillerPhone": "13812345678",
            "taxRatePercent": 6,
            "invoiceNumber": "12345678901234567890",
            "invoiceDate": "2026-10-10",
            "netAmountCent": 2264,
            "taxAmountCent": 136,
            "invoiceAmountCent": 2400,
            "allocations": _with_current_promotion_group_ids(
                client,
                store_id="store-1",
                allocations=[
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
            ),
        },
        headers={"Idempotency-Key": "promotion-invoice-register-0001"},
    )
    assert registered.status_code == 200
    registered_data = registered.json()["data"]
    assert registered_data["status"] == "SUBMITTED_PENDING_FACTORY_REVIEW"
    assert registered_data["buyerName"] == "比亚迪汽车销售有限公司"
    assert registered_data["taxRatePercent"] == 6
    assert registered_data["netAmountCent"] == 2264
    assert registered_data["taxAmountCent"] == 136
    assert registered_data["registeredAt"] == "2026-10-10T23:59:59+08:00"
    assert len(registered_data["allocations"]) == 2
    assert {
        allocation["settlementBatchMonth"]
        for allocation in registered_data["allocations"]
    } == {"2026-09"}

    persisted_invoice = db_session.scalar(select(PromotionInvoice))
    assert persisted_invoice is not None
    assert persisted_invoice.buyer_name == "比亚迪汽车销售有限公司"
    assert persisted_invoice.tax_rate_percent == 6
    assert persisted_invoice.filler_phone_ciphertext != "13812345678"
    assert persisted_invoice.net_amount_cent == 2264
    assert persisted_invoice.tax_amount_cent == 136
    persisted_allocations = list(db_session.scalars(select(PromotionInvoiceAllocation)))
    assert {allocation.settlement_batch_month for allocation in persisted_allocations} == {
        "2026-09"
    }

    listed = client.get(
        "/api/v1/promotion-invoices",
        params={"storeId": "store-1", "month": "2026-08"},
    )
    assert listed.status_code == 200
    listed_row = listed.json()["data"]["list"][0]
    assert listed_row["invoiceNumber"] == "12345678901234567890"
    assert listed_row["buyerName"] == "比亚迪汽车销售有限公司"
    assert listed_row["taxRatePercent"] == 6
    assert listed_row["netAmountCent"] == 2264
    assert listed_row["taxAmountCent"] == 136
    assert listed_row["settlementBatchMonth"] == "2026-09"


def test_promotion_invoice_uses_current_settlement_batch_from_beijing_day_11(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2026, 10, 10, 16, 0, 0, tzinfo=timezone.utc),
    )
    _login(client)
    confirmation = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json={
            "feeDirection": "PROMOTION",
            "confirmedAmountCent": 1100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "promotion-day-11-confirmation-key"},
    )
    assert confirmation.status_code == 200

    _act_as_store(client)
    registered = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "22345678901234567890",
            "invoiceDate": "2026-10-11",
            "invoiceAmountCent": 1100,
            **_manual_invoice_fields(1100),
            "allocations": _with_current_promotion_group_ids(
                client,
                store_id="store-1",
                allocations=[
                {
                    "statementId": "statement-1-v2",
                    "statementMonth": "2026-08",
                    "allocatedAmountCent": 1100,
                    "readVersion": 2,
                }
                ],
            ),
        },
        headers={"Idempotency-Key": "promotion-day-11-register-key"},
    )

    assert registered.status_code == 200
    data = registered.json()["data"]
    assert data["registeredAt"] == "2026-10-11T00:00:00+08:00"
    assert data["allocations"][0]["settlementBatchMonth"] == "2026-10"


@pytest.mark.parametrize(
    ("case_id", "field", "value"),
    [
        ("buyer-missing", "buyerName", None),
        ("buyer-wrong", "buyerName", "其他购买方"),
        ("tax-missing", "taxRatePercent", None),
        ("tax-wrong", "taxRatePercent", 5),
    ],
)
def test_promotion_invoice_rejects_missing_or_incorrect_fixed_billing_facts(
    client: TestClient,
    case_id: str,
    field: str,
    value: object,
) -> None:
    _login(client)
    confirmation = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json={
            "feeDirection": "PROMOTION",
            "confirmedAmountCent": 1100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": f"promotion-fixed-fact-confirmation-{case_id}"},
    )
    assert confirmation.status_code == 200
    payload = {
        "storeId": "store-1",
        "buyerName": "比亚迪汽车销售有限公司",
        "fillerPhone": "13812345678",
        "taxRatePercent": 6,
        "invoiceNumber": "32345678901234567890",
        "invoiceDate": "2026-10-11",
        "netAmountCent": 1038,
        "taxAmountCent": 62,
        "invoiceAmountCent": 1100,
        "allocations": [
            {
                "statementId": "statement-1-v2",
                "statementMonth": "2026-08",
                "allocatedAmountCent": 1100,
                "readVersion": 2,
            }
        ],
    }
    if value is None:
        payload.pop(field)
    else:
        payload[field] = value

    _act_as_store(client)
    response = client.post(
        "/api/v1/promotion-invoices",
        json=payload,
        headers={"Idempotency-Key": f"promotion-fixed-fact-register-{case_id}"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["field"] == field


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fillerPhone", None),
        ("fillerPhone", ""),
        ("netAmountCent", None),
        ("taxAmountCent", None),
    ],
)
def test_promotion_invoice_requires_manual_registration_fields(
    client: TestClient,
    field: str,
    value: object,
) -> None:
    _login(client)
    confirmation = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json={
            "feeDirection": "PROMOTION",
            "confirmedAmountCent": 1100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": f"invoice-manual-field-confirm-{field}-{value}"},
    )
    assert confirmation.status_code == 200
    payload = {
        "storeId": "store-1",
        "buyerName": "比亚迪汽车销售有限公司",
        "fillerPhone": "13812345678",
        "taxRatePercent": 6,
        "invoiceNumber": "33345678901234567890",
        "invoiceDate": "2026-10-11",
        "netAmountCent": 1038,
        "taxAmountCent": 62,
        "invoiceAmountCent": 1100,
        "allocations": [{
            "statementId": "statement-1-v2",
            "statementMonth": "2026-08",
            "allocatedAmountCent": 1100,
            "readVersion": 2,
        }],
    }
    if value is None:
        payload.pop(field)
    else:
        payload[field] = value
    _act_as_store(client)

    response = client.post(
        "/api/v1/promotion-invoices",
        json=payload,
        headers={"Idempotency-Key": f"invoice-manual-field-register-{field}-{value}"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["field"] == field


def test_promotion_invoice_allows_one_cent_identity_tolerance_but_rejects_two(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2026, 10, 11, 4, 0, 0, tzinfo=timezone.utc),
    )
    _login(client)
    confirmation = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json={
            "feeDirection": "PROMOTION",
            "confirmedAmountCent": 1100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "invoice-identity-confirm"},
    )
    assert confirmation.status_code == 200
    allocations = _with_current_promotion_group_ids(
        client,
        store_id="store-1",
        allocations=[{
            "statementId": "statement-1-v2",
            "statementMonth": "2026-08",
            "allocatedAmountCent": 1100,
            "readVersion": 2,
        }],
    )
    base_payload = {
        "storeId": "store-1",
        "buyerName": "比亚迪汽车销售有限公司",
        "fillerPhone": "13812345678",
        "taxRatePercent": 6,
        "invoiceDate": "2026-10-11",
        "netAmountCent": 1037,
        "taxAmountCent": 62,
        "invoiceAmountCent": 1100,
        "allocations": allocations,
    }
    _act_as_store(client)
    accepted = client.post(
        "/api/v1/promotion-invoices",
        json={**base_payload, "invoiceNumber": "34345678901234567890"},
        headers={"Idempotency-Key": "invoice-identity-one-cent"},
    )
    assert accepted.status_code == 200

    base_payload["netAmountCent"] = 1036
    rejected = client.post(
        "/api/v1/promotion-invoices",
        json={**base_payload, "invoiceNumber": "34345678901234567891"},
        headers={"Idempotency-Key": "invoice-identity-two-cent"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["errors"][0]["field"] == "invoiceAmountCent"


def test_promotion_confirmation_preserves_signed_negative_amount(
    client: TestClient,
    db_session: Session,
) -> None:
    db_session.add(
        SettlementStatement(
            statement_id="statement-negative-confirmation",
            store_id="store-1",
            statement_month="2026-10",
            version_no=1,
            is_current=True,
            statement_status=4,
            promotion_original_fee_cent=0,
            promotion_adjustment_fee_cent=-150,
            promotion_net_fee_cent=-150,
            management_original_fee_cent=0,
            management_adjustment_fee_cent=0,
            management_net_fee_cent=0,
        )
    )
    db_session.commit()
    _login(client)

    response = client.post(
        "/api/v1/store-settlements/statement-negative-confirmation/confirmations",
        json={
            "feeDirection": "PROMOTION",
            "confirmedAmountCent": -150,
            "readVersion": 1,
        },
        headers={"Idempotency-Key": "negative-confirmation-key-0001"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["confirmedAmountCent"] == -150


def test_promotion_carryforward_projection_offsets_late_negative_against_earliest_positive(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_confirmed_promotion_periods(
        db_session,
        store_id="store-1",
        periods=[
            ("statement-carry-positive-oct", "2026-10", 100),
            ("statement-carry-negative-nov", "2026-11", -150),
            ("statement-carry-positive-dec", "2026-12", 100),
            ("statement-carry-positive-jan", "2027-01", 200),
        ],
    )
    _login(client)

    projected: dict[str, dict] = {}
    for month in ("2026-10", "2026-11", "2026-12", "2027-01"):
        response = client.get(
            "/api/v1/store-settlements",
            params={
                "storeId": "store-1",
                "month": month,
                "metricScope": "MONTH",
                "feeDirection": "PROMOTION",
            },
        )
        assert response.status_code == 200
        projected[month] = response.json()["data"]["list"][0]

    carry_group_id = projected["2026-10"]["promotionInvoiceGroupId"]
    assert carry_group_id
    assert {
        projected[month]["promotionInvoiceGroupId"]
        for month in ("2026-10", "2026-11", "2026-12")
    } == {carry_group_id}
    assert projected["2026-10"]["promotionRequiredStatementIds"] == [
        "statement-carry-positive-oct",
        "statement-carry-negative-nov",
        "statement-carry-positive-dec",
    ]
    assert projected["2026-10"]["promotionCarryforwardBalanceCent"] == 0
    assert projected["2026-11"]["promotionCarryforwardBalanceCent"] == -50
    assert projected["2026-12"]["promotionCarryforwardBalanceCent"] == 0
    assert {
        projected[month]["promotionInvoiceableAmountCent"]
        for month in ("2026-10", "2026-11", "2026-12")
    } == {50}
    assert projected["2027-01"]["promotionInvoiceableAmountCent"] == 200
    assert projected["2027-01"]["promotionInvoiceGroupId"] != carry_group_id

    monthly_summary = client.get(
        "/api/v1/admin/finance/summary",
        params={
            "month": "2026-12",
            "storeId": "store-1",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )
    cumulative_summary = client.get(
        "/api/v1/admin/finance/summary",
        params={
            "month": "2026-12",
            "storeId": "store-1",
            "feeDirection": "PROMOTION",
            "metricScope": "CUMULATIVE",
        },
    )
    assert monthly_summary.status_code == cumulative_summary.status_code == 200
    assert monthly_summary.json()["data"]["metrics"]["pendingInvoiceAmountCent"] == 50
    assert cumulative_summary.json()["data"]["metrics"]["pendingInvoiceAmountCent"] == 50


def test_promotion_projection_excludes_effective_store_month_allocation_across_statement_versions(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_confirmed_promotion_periods(
        db_session,
        store_id="store-1",
        periods=[("statement-versioned-current", "2027-02", 100)],
    )
    current_statement = db_session.get(
        SettlementStatement,
        db_session.scalar(
            select(SettlementStatement.id).where(
                SettlementStatement.statement_id == "statement-versioned-current"
            )
        ),
    )
    assert current_statement is not None
    current_statement.version_no = 2
    current_statement.supersedes_statement_id = "statement-versioned-old"
    # Persist the version bump before inserting the retired v1 row so the
    # store/month/version uniqueness invariant is never transiently violated.
    db_session.flush()
    db_session.add_all(
        [
            SettlementStatement(
                statement_id="statement-versioned-old",
                store_id="store-1",
                statement_month="2027-02",
                version_no=1,
                is_current=False,
                statement_status=4,
                promotion_original_fee_cent=100,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=100,
                management_original_fee_cent=0,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=0,
            ),
            PromotionInvoice(
                invoice_id="invoice-versioned-period",
                physical_invoice_id="physical-versioned-period",
                store_id="store-1",
                version_no=1,
                version_kind=1,
                is_current=True,
                invoice_number="72345678901234567890",
                invoice_date=date(2027, 2, 20),
                invoice_amount_cent=100,
                buyer_name="BYD",
                tax_rate_percent=6,
                invoice_status=2,
                registered_by="store-user",
                registered_at=datetime(2027, 2, 20, tzinfo=timezone.utc),
            ),
            PromotionInvoiceAllocation(
                allocation_id="allocation-versioned-period",
                invoice_id="invoice-versioned-period",
                store_id="store-1",
                statement_id="statement-versioned-old",
                statement_month="2027-02",
                settlement_batch_month="2027-01",
                allocated_amount_cent=100,
                is_current=True,
            ),
        ]
    )
    db_session.commit()
    _login(client)

    statements = client.get(
        "/api/v1/store-settlements",
        params={
            "storeId": "store-1",
            "month": "2027-02",
            "metricScope": "MONTH",
            "feeDirection": "PROMOTION",
        },
    )
    summary = client.get(
        "/api/v1/admin/finance/summary",
        params={
            "month": "2027-02",
            "storeId": "store-1",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )

    assert statements.status_code == summary.status_code == 200
    statement = statements.json()["data"]["list"][0]
    assert statement["promotionInvoiceGroupId"] is None
    assert statement["promotionInvoiceableAmountCent"] == 0
    assert statement["promotionInvoiceStatus"] == "SUBMITTED_PENDING_FACTORY_REVIEW"
    assert summary.json()["data"]["metrics"]["issuedAmountCent"] == 100


def test_zero_promotion_confirmation_is_excluded_from_invoice_groups(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_confirmed_promotion_periods(
        db_session,
        store_id="store-1",
        periods=[("statement-zero-confirmation", "2027-03", 0)],
    )
    _login(client)

    response = client.get(
        "/api/v1/store-settlements",
        params={
            "storeId": "store-1",
            "month": "2027-03",
            "metricScope": "MONTH",
            "feeDirection": "PROMOTION",
        },
    )

    assert response.status_code == 200
    statement = response.json()["data"]["list"][0]
    assert statement["promotionInvoiceGroupId"] is None
    assert statement["promotionRequiredStatementIds"] == []
    assert statement["promotionInvoiceableAmountCent"] == 0


def test_promotion_registration_reprojects_after_locking_selected_group(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2027, 4, 21, 4, 0, 0, tzinfo=timezone.utc),
    )
    _seed_confirmed_promotion_periods(
        db_session,
        store_id="store-1",
        periods=[("statement-reproject-lock", "2027-04", 100)],
    )
    _login(client)
    projection = client.get(
        "/api/v1/store-settlements",
        params={
            "storeId": "store-1",
            "month": "2027-04",
            "metricScope": "MONTH",
            "feeDirection": "PROMOTION",
        },
    ).json()["data"]["list"][0]
    original_projection = dashboard_routes._promotion_invoice_carryforward_projection
    call_count = 0

    def changed_after_first_projection(session, *, store_id=None):
        nonlocal call_count
        call_count += 1
        projected, groups = original_projection(session, store_id=store_id)
        if call_count == 1:
            return projected, groups
        changed_projection = {
            statement_id: {**item, "group_id": f"{item['group_id']}-changed"}
            for statement_id, item in projected.items()
        }
        changed_groups = [
            {**group, "group_id": f"{group['group_id']}-changed"}
            for group in groups
        ]
        return changed_projection, changed_groups

    monkeypatch.setattr(
        dashboard_routes,
        "_promotion_invoice_carryforward_projection",
        changed_after_first_projection,
    )
    _act_as_store(client)
    response = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "82345678901234567890",
            "invoiceDate": "2027-04-20",
            "invoiceAmountCent": 100,
            **_manual_invoice_fields(100),
            "allocations": [
                {
                    "statementId": "statement-reproject-lock",
                    "statementMonth": "2027-04",
                    "allocatedAmountCent": 100,
                    "readVersion": 1,
                    "promotionInvoiceGroupId": projection[
                        "promotionInvoiceGroupId"
                    ],
                }
            ],
        },
        headers={"Idempotency-Key": "promotion-reproject-lock-0001"},
    )

    assert call_count >= 2
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PROMOTION_INVOICE_GROUP_CHANGED"


def test_promotion_invoice_registration_requires_complete_current_group(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2026, 12, 21, 4, 0, 0, tzinfo=timezone.utc),
    )
    periods = [
        ("statement-group-negative", "2026-10", -150),
        ("statement-group-positive-1", "2026-11", 100),
        ("statement-group-positive-2", "2026-12", 100),
    ]
    _seed_confirmed_promotion_periods(
        db_session,
        store_id="store-1",
        periods=periods,
    )
    _login(client)
    projection = client.get(
        "/api/v1/store-settlements",
        params={
            "storeId": "store-1",
            "month": "2026-12",
            "metricScope": "MONTH",
            "feeDirection": "PROMOTION",
        },
    ).json()["data"]["list"][0]
    group_id = projection["promotionInvoiceGroupId"]

    _act_as_store(client)
    partial = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "42345678901234567890",
            "invoiceDate": "2026-12-20",
            "invoiceAmountCent": 100,
            **_manual_invoice_fields(100),
            "allocations": [
                {
                    "statementId": "statement-group-positive-2",
                    "statementMonth": "2026-12",
                    "allocatedAmountCent": 100,
                    "readVersion": 1,
                    "promotionInvoiceGroupId": group_id,
                }
            ],
        },
        headers={"Idempotency-Key": "promotion-partial-group-0001"},
    )
    stale = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "42345678901234567891",
            "invoiceDate": "2026-12-20",
            "invoiceAmountCent": 50,
            **_manual_invoice_fields(50),
            "allocations": [
                {
                    "statementId": statement_id,
                    "statementMonth": statement_month,
                    "allocatedAmountCent": amount,
                    "readVersion": 1,
                    "promotionInvoiceGroupId": "stale-group-id",
                }
                for statement_id, statement_month, amount in periods
            ],
        },
        headers={"Idempotency-Key": "promotion-stale-group-0001"},
    )

    assert partial.status_code == 422
    assert partial.json()["detail"]["code"] == "PROMOTION_INVOICE_GROUP_INCOMPLETE"
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "PROMOTION_INVOICE_GROUP_CHANGED"


def test_promotion_invoice_registration_requires_all_current_invoiceable_groups(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A store cannot omit another invoiceable period from the single invoice."""

    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2026, 12, 21, 4, 0, 0, tzinfo=timezone.utc),
    )
    _seed_confirmed_promotion_periods(
        db_session,
        store_id="store-1",
        periods=[
            ("statement-all-periods-1", "2026-11", 100),
            ("statement-all-periods-2", "2026-12", 100),
        ],
    )
    _login(client)
    allocations = _with_current_promotion_group_ids(
        client,
        store_id="store-1",
        allocations=[
            {
                "statementId": "statement-all-periods-1",
                "statementMonth": "2026-11",
                "allocatedAmountCent": 100,
                "readVersion": 1,
            }
        ],
    )

    _act_as_store(client)
    response = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "43345678901234567890",
            "invoiceDate": "2026-12-20",
            "invoiceAmountCent": 100,
            **_manual_invoice_fields(100),
            "allocations": allocations,
        },
        headers={"Idempotency-Key": "promotion-all-groups-required-0001"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == (
        "PROMOTION_INVOICE_SELECTION_INCOMPLETE"
    )


def test_promotion_invoice_registration_accepts_signed_complete_group(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2026, 12, 21, 4, 0, 0, tzinfo=timezone.utc),
    )
    periods = [
        ("statement-register-negative", "2026-10", -150),
        ("statement-register-positive-1", "2026-11", 100),
        ("statement-register-positive-2", "2026-12", 100),
    ]
    _seed_confirmed_promotion_periods(
        db_session,
        store_id="store-1",
        periods=periods,
    )
    _login(client)
    projection = client.get(
        "/api/v1/store-settlements",
        params={
            "storeId": "store-1",
            "month": "2026-12",
            "metricScope": "MONTH",
            "feeDirection": "PROMOTION",
        },
    ).json()["data"]["list"][0]
    group_id = projection["promotionInvoiceGroupId"]

    _act_as_store(client)
    response = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "52345678901234567890",
            "invoiceDate": "2026-12-20",
            "invoiceAmountCent": 50,
            **_manual_invoice_fields(50),
            "allocations": [
                {
                    "statementId": statement_id,
                    "statementMonth": statement_month,
                    "allocatedAmountCent": amount,
                    "readVersion": 1,
                    "promotionInvoiceGroupId": group_id,
                }
                for statement_id, statement_month, amount in periods
            ],
        },
        headers={"Idempotency-Key": "promotion-signed-group-0001"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["invoiceAmountCent"] == 50
    allocations = list(
        db_session.scalars(
            select(PromotionInvoiceAllocation).where(
                PromotionInvoiceAllocation.invoice_id
                == response.json()["data"]["invoiceId"]
            )
        )
    )
    assert [row.allocated_amount_cent for row in allocations] == [-150, 100, 100]


def test_replacement_includes_released_period_and_complete_new_carryforward_group(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2026, 12, 21, 4, 0, 0, tzinfo=timezone.utc),
    )
    periods = [
        ("statement-released-positive", "2026-10", 100),
        ("statement-after-negative", "2026-11", -150),
        ("statement-after-positive", "2026-12", 100),
    ]
    _seed_confirmed_promotion_periods(
        db_session,
        store_id="store-1",
        periods=periods,
    )
    old_invoice_id = "promotion-invoice-released-carryforward"
    old_physical_id = "physical-invoice-released-carryforward"
    old_number = "62345678901234567890"
    db_session.add_all(
        [
            PromotionInvoice(
                invoice_id=old_invoice_id,
                physical_invoice_id=old_physical_id,
                store_id="store-1",
                version_no=1,
                version_kind=1,
                is_current=True,
                invoice_number=old_number,
                invoice_date=date(2026, 10, 10),
                invoice_amount_cent=100,
                buyer_name="比亚迪汽车销售有限公司",
                tax_rate_percent=6,
                invoice_status=3,
                registered_by="store-user",
                registered_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
            ),
            PromotionInvoiceNumberRegistry(
                invoice_number=old_number,
                physical_invoice_id=old_physical_id,
                first_invoice_id=old_invoice_id,
                store_id="store-1",
                registered_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
            ),
            PromotionInvoiceAllocation(
                allocation_id="allocation-released-carryforward",
                invoice_id=old_invoice_id,
                store_id="store-1",
                statement_id="statement-released-positive",
                statement_month="2026-10",
                settlement_batch_month="2026-09",
                allocated_amount_cent=100,
                is_current=True,
            ),
        ]
    )
    db_session.commit()
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="store-user",
        username="store-user",
        display_name="Store User",
        role="store",
        store_ids=("store-1",),
        auth_type="user",
        store_scope_mode="assigned",
    )
    terminated = client.post(
        f"/api/v1/promotion-invoices/{old_invoice_id}/lifecycle-events",
        json={"eventType": "VOIDED", "reason": "系统外作废", "readVersion": 1},
        headers={"Idempotency-Key": "released-carryforward-void-0001"},
    )
    assert terminated.status_code == 200
    allocations = _with_current_promotion_group_ids(
        client,
        store_id="store-1",
        allocations=[
            {
                "statementId": statement_id,
                "statementMonth": statement_month,
                "allocatedAmountCent": amount,
                "readVersion": 1,
            }
            for statement_id, statement_month, amount in periods
        ],
    )
    replacement = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "62345678901234567891",
            "invoiceDate": "2026-12-20",
            "invoiceAmountCent": 50,
            **_manual_invoice_fields(50),
            "replacesInvoiceId": old_invoice_id,
            "allocations": allocations,
        },
        headers={"Idempotency-Key": "released-carryforward-replace-0001"},
    )
    assert replacement.status_code == 200
    assert replacement.json()["data"]["invoiceAmountCent"] == 50


def test_one_replacement_can_cover_multiple_terminated_invoices_in_one_group(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2026, 12, 21, 4, 0, 0, tzinfo=timezone.utc),
    )
    periods = [
        ("statement-multi-source-oct", "2026-10", 100),
        ("statement-multi-source-nov", "2026-11", -150),
        ("statement-multi-source-dec", "2026-12", 100),
    ]
    _seed_confirmed_promotion_periods(
        db_session,
        store_id="store-1",
        periods=periods,
    )
    source_rows = [
        (
            "promotion-multi-source-oct",
            "physical-multi-source-oct",
            "71345678901234567890",
            "statement-multi-source-oct",
            "2026-10",
        ),
        (
            "promotion-multi-source-dec",
            "physical-multi-source-dec",
            "71345678901234567891",
            "statement-multi-source-dec",
            "2026-12",
        ),
    ]
    for invoice_id, physical_id, number, statement_id, month in source_rows:
        db_session.add_all(
            [
                PromotionInvoice(
                    invoice_id=invoice_id,
                    physical_invoice_id=physical_id,
                    store_id="store-1",
                    version_no=1,
                    version_kind=1,
                    is_current=True,
                    invoice_number=number,
                    invoice_date=date(2026, 10, 10),
                    invoice_amount_cent=100,
                    buyer_name="比亚迪汽车销售有限公司",
                    tax_rate_percent=6,
                    invoice_status=3,
                    registered_by="store-user",
                    registered_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
                ),
                PromotionInvoiceNumberRegistry(
                    invoice_number=number,
                    physical_invoice_id=physical_id,
                    first_invoice_id=invoice_id,
                    store_id="store-1",
                    registered_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
                ),
                PromotionInvoiceAllocation(
                    allocation_id=f"allocation-{invoice_id}",
                    invoice_id=invoice_id,
                    store_id="store-1",
                    statement_id=statement_id,
                    statement_month=month,
                    settlement_batch_month="2026-09",
                    allocated_amount_cent=100,
                    is_current=True,
                ),
            ]
        )
    db_session.commit()
    _act_as_store(client)
    for index, (invoice_id, *_rest) in enumerate(source_rows, start=1):
        response = client.post(
            f"/api/v1/promotion-invoices/{invoice_id}/lifecycle-events",
            json={
                "eventType": "VOIDED",
                "reason": "系统外作废后合并重开",
                "readVersion": 1,
            },
            headers={"Idempotency-Key": f"multi-source-void-{index:04d}"},
        )
        assert response.status_code == 200

    allocations = _with_current_promotion_group_ids(
        client,
        store_id="store-1",
        allocations=[
            {
                "statementId": statement_id,
                "statementMonth": month,
                "allocatedAmountCent": amount,
                "readVersion": 1,
            }
            for statement_id, month, amount in periods
        ],
    )
    response = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "71345678901234567892",
            "invoiceDate": "2026-12-20",
            "invoiceAmountCent": 50,
            **_manual_invoice_fields(50),
            "replacesInvoiceId": source_rows[0][0],
            "allocations": allocations,
        },
        headers={"Idempotency-Key": "multi-source-replacement-0001"},
    )

    assert response.status_code == 200
    replacement_id = response.json()["data"]["invoiceId"]
    links = list(
        db_session.scalars(
            select(PromotionInvoiceReplacementSource).where(
                PromotionInvoiceReplacementSource.replacement_invoice_id
                == replacement_id
            )
        )
    )
    assert {link.source_invoice_id for link in links} == {
        source_rows[0][0],
        source_rows[1][0],
    }
    assert db_session.scalar(
        select(func.count())
        .select_from(PromotionInvoiceLifecycleEvent)
        .where(PromotionInvoiceLifecycleEvent.is_current.is_(True))
    ) == 0
    detail = client.get(f"/api/v1/promotion-invoices/{replacement_id}")
    assert detail.status_code == 200
    assert {
        item["invoiceId"]
        for item in detail.json()["data"]["replacementChain"]
    } == {source_rows[0][0], source_rows[1][0], replacement_id}


def test_rejected_promotion_invoice_can_be_terminated_then_replaced(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2026, 10, 10, 4, 0, 0, tzinfo=timezone.utc),
    )
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

    allocations = _with_current_promotion_group_ids(
        client,
        store_id="store-1",
        allocations=allocations,
    )
    _act_as_store(client)
    first = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "12345678901234567890",
            "invoiceDate": "2026-10-10",
            "invoiceAmountCent": 2400,
            **_manual_invoice_fields(2400),
            "allocations": allocations,
        },
        headers={"Idempotency-Key": "reupload-invoice-register-0001"},
    )
    assert first.status_code == 200
    previous = db_session.scalar(select(PromotionInvoice))
    assert previous is not None
    previous.invoice_status = 4
    db_session.commit()
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="store-user", username="store-user", display_name="Store User",
        role="store", store_ids=("store-1",), auth_type="user",
        store_scope_mode="assigned",
    )
    terminated = client.post(
        f"/api/v1/promotion-invoices/{previous.invoice_id}/lifecycle-events",
        json={"eventType": "VOIDED", "reason": "系统外作废后重新开票", "readVersion": 1},
        headers={"Idempotency-Key": "reupload-invoice-void-0001"},
    )
    assert terminated.status_code == 200
    allocations = _with_current_promotion_group_ids(
        client,
        store_id="store-1",
        allocations=[
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
    )

    incomplete_replacement = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "08876543210987654321",
            "invoiceDate": "2026-10-10",
            "invoiceAmountCent": 1100,
            **_manual_invoice_fields(1100),
            "replacesInvoiceId": previous.invoice_id,
            "allocations": allocations[:1],
        },
        headers={"Idempotency-Key": "reupload-invoice-incomplete-0001"},
    )
    assert incomplete_replacement.status_code == 422
    assert incomplete_replacement.json()["detail"]["code"] == (
        "PROMOTION_INVOICE_SELECTION_INCOMPLETE"
    )

    reused_number = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "12345678901234567890",
            "invoiceDate": "2026-10-10",
            "invoiceAmountCent": 2400,
            **_manual_invoice_fields(2400),
            "replacesInvoiceId": previous.invoice_id,
            "allocations": allocations,
        },
        headers={"Idempotency-Key": "reupload-invoice-number-reuse-0001"},
    )
    assert reused_number.status_code == 409
    assert reused_number.json()["detail"]["code"] == "PROMOTION_INVOICE_NUMBER_REUSED"

    replacement = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "09876543210987654321",
            "invoiceDate": "2026-10-10",
            "invoiceAmountCent": 2400,
            **_manual_invoice_fields(2400),
            "replacesInvoiceId": previous.invoice_id,
            "allocations": allocations,
        },
        headers={"Idempotency-Key": "reupload-invoice-register-0002"},
    )

    assert replacement.status_code == 200
    assert replacement.json()["data"]["versionNo"] == 1
    assert replacement.json()["data"]["supersedesInvoiceId"] is None
    assert replacement.json()["data"]["replacesInvoiceId"] == previous.invoice_id
    db_session.expire_all()
    assert db_session.scalar(
        select(PromotionInvoice.is_current).where(
            PromotionInvoice.invoice_id == previous.invoice_id
        )
    ) is False


def test_store_records_external_void_and_replaces_all_released_periods(
    client: TestClient, db_session: Session
) -> None:
    physical_id = "physical-invoice-lifecycle-v1"
    old_invoice_id = "promotion-invoice-lifecycle-v1"
    old_number = "71345678901234567890"
    new_number = "71345678901234567891"
    db_session.add_all([
        PromotionInvoice(
            invoice_id=old_invoice_id, physical_invoice_id=physical_id,
            store_id="store-1", version_no=1, version_kind=1, is_current=True,
            invoice_number=old_number, invoice_date=date(2026, 8, 10),
            invoice_amount_cent=1100, buyer_name="比亚迪汽车销售有限公司",
            tax_rate_percent=6, invoice_status=3, registered_by="store-user",
            registered_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        ),
        PromotionInvoiceNumberRegistry(
            invoice_number=old_number, physical_invoice_id=physical_id,
            first_invoice_id=old_invoice_id, store_id="store-1",
            registered_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        ),
        PromotionInvoiceAllocation(
            allocation_id="promotion-allocation-lifecycle-v1",
            invoice_id=old_invoice_id, store_id="store-1",
            statement_id="statement-1-v2", statement_month="2026-08",
            settlement_batch_month="2026-07", allocated_amount_cent=1100,
            is_current=True,
        ),
        SettlementStatementConfirmation(
            confirmation_id="confirmation-lifecycle-replacement",
            statement_id="statement-1-v2", fee_direction=1,
            confirmation_status=1, confirmed_amount_cent=1100,
            confirmed_by="store-user",
            confirmed_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        ),
    ])
    db_session.commit()
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="store-user", username="store-user", display_name="Store User",
        role="store", store_ids=("store-1",), auth_type="user",
        store_scope_mode="assigned",
    )
    body = {"eventType": "VOIDED", "reason": "系统外已完成作废", "readVersion": 1}
    terminated = client.post(
        f"/api/v1/promotion-invoices/{old_invoice_id}/lifecycle-events",
        json=body, headers={"Idempotency-Key": "promotion-lifecycle-void-0001"},
    )
    replay = client.post(
        f"/api/v1/promotion-invoices/{old_invoice_id}/lifecycle-events",
        json=body, headers={"Idempotency-Key": "promotion-lifecycle-void-0001"},
    )
    assert terminated.status_code == replay.status_code == 200
    assert terminated.json()["data"]["releasedStatementMonths"] == ["2026-08"]
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="store-2-user", username="store-2-user", display_name="Store 2 User",
        role="store", store_ids=("store-2",), auth_type="user",
        store_scope_mode="assigned",
    )
    forbidden_replay = client.post(
        f"/api/v1/promotion-invoices/{old_invoice_id}/lifecycle-events",
        json=body,
        headers={"Idempotency-Key": "promotion-lifecycle-void-0001"},
    )
    assert forbidden_replay.status_code == 403
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="store-user", username="store-user", display_name="Store User",
        role="store", store_ids=("store-1",), auth_type="user",
        store_scope_mode="assigned",
    )
    idempotency_conflict = client.post(
        f"/api/v1/promotion-invoices/{old_invoice_id}/lifecycle-events",
        json={**body, "reason": "同一幂等键的不同原因"},
        headers={"Idempotency-Key": "promotion-lifecycle-void-0001"},
    )
    assert idempotency_conflict.status_code == 409
    assert idempotency_conflict.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    second = client.post(
        f"/api/v1/promotion-invoices/{old_invoice_id}/lifecycle-events",
        json={"eventType": "RED_FLUSHED", "reason": "重复终止", "readVersion": 1},
        headers={"Idempotency-Key": "promotion-lifecycle-red-0002"},
    )
    assert second.status_code == 409
    missing_replacement_link = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1", "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6, "invoiceNumber": "71345678901234567899",
            "invoiceDate": "2026-08-20", "invoiceAmountCent": 1100,
            **_manual_invoice_fields(1100),
            "allocations": _with_current_promotion_group_ids(
                client,
                store_id="store-1",
                allocations=[{
                    "statementId": "statement-1-v2", "statementMonth": "2026-08",
                    "allocatedAmountCent": 1100, "readVersion": 2,
                }],
            ),
        },
        headers={"Idempotency-Key": "promotion-replacement-link-required-0001"},
    )
    assert missing_replacement_link.status_code == 409
    assert missing_replacement_link.json()["detail"]["code"] == (
        "PROMOTION_INVOICE_REPLACEMENT_REQUIRED"
    )
    replacement = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1", "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6, "invoiceNumber": new_number,
            "invoiceDate": "2026-08-20", "invoiceAmountCent": 1100,
            **_manual_invoice_fields(1100),
            "replacesInvoiceId": old_invoice_id,
            "allocations": _with_current_promotion_group_ids(
                client,
                store_id="store-1",
                allocations=[{
                    "statementId": "statement-1-v2", "statementMonth": "2026-08",
                    "allocatedAmountCent": 1100, "readVersion": 2,
                }],
            ),
        },
        headers={"Idempotency-Key": "promotion-replacement-register-0001"},
    )
    assert replacement.status_code == 200
    data = replacement.json()["data"]
    assert data["replacesInvoiceId"] == old_invoice_id
    assert data["supersedesInvoiceId"] is None
    assert data["physicalInvoiceId"] != physical_id
    detail = client.get(f"/api/v1/promotion-invoices/{old_invoice_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["lifecycleEvents"][0]["eventType"] == "VOIDED"
    assert detail.json()["data"]["replacements"][0]["invoiceNumber"] == new_number
    terminated_replacement = client.post(
        f"/api/v1/promotion-invoices/{data['invoiceId']}/lifecycle-events",
        json={"eventType": "RED_FLUSHED", "reason": "系统外红冲替换发票", "readVersion": 1},
        headers={"Idempotency-Key": "promotion-lifecycle-red-successor-0001"},
    )
    assert terminated_replacement.status_code == 200
    released_allocations = _with_current_promotion_group_ids(
        client,
        store_id="store-1",
        allocations=[{
            "statementId": "statement-1-v2", "statementMonth": "2026-08",
            "allocatedAmountCent": 1100, "readVersion": 2,
        }],
    )
    branch = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1", "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6, "invoiceNumber": "71345678901234567892",
            "invoiceDate": "2026-08-21", "invoiceAmountCent": 1100,
            **_manual_invoice_fields(1100),
            "replacesInvoiceId": old_invoice_id,
            "allocations": released_allocations,
        },
        headers={"Idempotency-Key": "promotion-replacement-branch-0001"},
    )
    assert branch.status_code == 409
    assert branch.json()["detail"]["code"] == "PROMOTION_INVOICE_REPLACEMENT_REQUIRED"
    second_replacement = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1", "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6, "invoiceNumber": "71345678901234567893",
            "invoiceDate": "2026-08-21", "invoiceAmountCent": 1100,
            **_manual_invoice_fields(1100),
            "replacesInvoiceId": data["invoiceId"],
            "allocations": released_allocations,
        },
        headers={"Idempotency-Key": "promotion-replacement-chain-0001"},
    )
    assert second_replacement.status_code == 200
    chain_detail = client.get(f"/api/v1/promotion-invoices/{old_invoice_id}")
    assert [
        item["invoiceNumber"]
        for item in chain_detail.json()["data"]["replacementChain"]
    ] == [old_number, new_number, "71345678901234567893"]
    data = second_replacement.json()["data"]
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="admin-user", username="admin-user", display_name="Admin User",
        role="admin", store_ids=(), auth_type="user", store_scope_mode="all",
    )
    allowed = client.post(
        f"/api/v1/promotion-invoices/{data['invoiceId']}/lifecycle-events",
        json={"eventType": "VOIDED", "reason": "管理员代操作", "readVersion": 1},
        headers={"Idempotency-Key": "promotion-admin-lifecycle-0001"},
    )
    assert allowed.status_code == 200
    assert db_session.scalar(select(func.count()).select_from(PromotionInvoiceLifecycleEvent)) == 3


def test_admin_with_global_scope_can_register_promotion_invoice(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dashboard_routes,
        "utcnow",
        lambda: datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    _login(client)
    confirmed = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json={
            "feeDirection": "PROMOTION",
            "confirmedAmountCent": 1100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "admin-register-confirmation-0001"},
    )
    assert confirmed.status_code == 200
    allocations = _with_current_promotion_group_ids(
        client,
        store_id="store-1",
        allocations=[{
            "statementId": "statement-1-v2",
            "statementMonth": "2026-08",
            "allocatedAmountCent": 1100,
            "readVersion": 2,
        }],
    )

    allowed = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": "73345678901234567890",
            "invoiceDate": "2026-08-28",
            "invoiceAmountCent": 1100,
            **_manual_invoice_fields(1100),
            "allocations": allocations,
        },
        headers={"Idempotency-Key": "admin-register-denied-0001"},
    )

    assert allowed.status_code == 200
    assert allowed.json()["data"]["invoiceNumber"] == "73345678901234567890"


def test_promotion_invoice_number_filter_is_exact_and_applied_before_pagination(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="exact-search-invoice",
        physical_invoice_id="exact-search-physical",
        invoice_number="74345678901234567891",
    )
    _act_as_store(client)

    exact = client.get(
        "/api/v1/promotion-invoices",
        params={
            "storeId": "store-1",
            "month": "2026-08",
            "invoiceNumber": "74345678901234567891",
            "page": 1,
            "pageSize": 1,
        },
    )
    partial = client.get(
        "/api/v1/promotion-invoices",
        params={
            "storeId": "store-1",
            "month": "2026-08",
            "invoiceNumber": "7434567890123456789",
            "page": 1,
            "pageSize": 1,
        },
    )

    assert exact.status_code == 200
    assert exact.json()["data"]["total"] == 1
    assert exact.json()["data"]["list"][0]["invoiceNumber"] == (
        "74345678901234567891"
    )
    assert partial.status_code == 200
    assert partial.json()["data"]["total"] == 0


@pytest.mark.parametrize(
    ("invoice_date", "expected_message"),
    [
        ("2026-08-27", "不得早于账单确认或锁账日期"),
        ("2026-08-29", "不得晚于服务器当前日期"),
    ],
)
def test_promotion_invoice_date_respects_statement_and_server_date_boundaries(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    invoice_date: str,
    expected_message: str,
) -> None:
    monkeypatch.setattr(
        "dy_api.routes.dashboard.utcnow",
        lambda: datetime(2026, 8, 28, 4, 0, tzinfo=timezone.utc),
    )
    _login(client)
    confirmed = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json={
            "feeDirection": "PROMOTION",
            "confirmedAmountCent": 1100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": f"invoice-date-confirm-{invoice_date}"},
    )
    assert confirmed.status_code == 200
    allocations = _with_current_promotion_group_ids(
        client,
        store_id="store-1",
        allocations=[{
            "statementId": "statement-1-v2",
            "statementMonth": "2026-08",
            "allocatedAmountCent": 1100,
            "readVersion": 2,
        }],
    )
    _act_as_store(client)

    response = client.post(
        "/api/v1/promotion-invoices",
        json={
            "storeId": "store-1",
            "buyerName": "比亚迪汽车销售有限公司",
            "taxRatePercent": 6,
            "invoiceNumber": (
                "75345678901234567890"
                if invoice_date.endswith("27")
                else "75345678901234567891"
            ),
            "invoiceDate": invoice_date,
            "invoiceAmountCent": 1100,
            **_manual_invoice_fields(1100),
            "allocations": allocations,
        },
        headers={"Idempotency-Key": f"invoice-date-register-{invoice_date}"},
    )

    assert response.status_code == 422
    assert expected_message in response.json()["detail"]["message"]


def test_lifecycle_replay_checks_store_scope_before_returning_original_result(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="scope-replay-invoice",
        physical_invoice_id="scope-replay-physical",
        invoice_number="74345678901234567890",
    )
    _act_as_store(client, "store-1")
    payload = {
        "eventType": "VOIDED",
        "reason": "系统外已作废",
        "readVersion": 1,
    }
    first = client.post(
        "/api/v1/promotion-invoices/scope-replay-invoice/lifecycle-events",
        json=payload,
        headers={"Idempotency-Key": "scope-replay-lifecycle-0001"},
    )
    assert first.status_code == 200

    _act_as_store(client, "store-2")
    forbidden_replay = client.post(
        "/api/v1/promotion-invoices/scope-replay-invoice/lifecycle-events",
        json={**payload, "reason": "跨门店探测幂等键"},
        headers={"Idempotency-Key": "scope-replay-lifecycle-0001"},
    )

    assert forbidden_replay.status_code == 403
    assert forbidden_replay.json()["detail"]["code"] == "DATA_SCOPE_FORBIDDEN"


def test_lifecycle_reason_over_1000_characters_returns_structured_422(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="reason-limit-invoice",
        physical_invoice_id="reason-limit-physical",
        invoice_number="75345678901234567890",
    )
    _act_as_store(client)

    response = client.post(
        "/api/v1/promotion-invoices/reason-limit-invoice/lifecycle-events",
        json={"eventType": "RED_FLUSHED", "reason": "原" * 1001, "readVersion": 1},
        headers={"Idempotency-Key": "reason-limit-lifecycle-0001"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["field"] == "reason"


@pytest.mark.parametrize("invoice_status", [2, 3, 4])
@pytest.mark.parametrize("event_type", ["RED_FLUSHED", "VOIDED"])
def test_lifecycle_event_matrix_accepts_every_factory_status(
    client: TestClient,
    db_session: Session,
    invoice_status: int,
    event_type: str,
) -> None:
    suffix = f"{invoice_status}{1 if event_type == 'RED_FLUSHED' else 2}"
    _seed_current_promotion_invoice(
        db_session,
        invoice_id=f"matrix-invoice-{suffix}",
        physical_invoice_id=f"matrix-physical-{suffix}",
        invoice_number=f"76{suffix}456789012345678"[:20],
        invoice_status=invoice_status,
    )
    _act_as_store(client)

    response = client.post(
        f"/api/v1/promotion-invoices/matrix-invoice-{suffix}/lifecycle-events",
        json={"eventType": event_type, "reason": "系统外事实", "readVersion": 1},
        headers={"Idempotency-Key": f"matrix-lifecycle-{suffix}-0001"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["lifecycleEvent"]["eventType"] == event_type


def test_lifecycle_commit_race_replays_the_winning_result(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="race-replay-invoice",
        physical_invoice_id="race-replay-physical",
        invoice_number="77345678901234567890",
    )
    _act_as_store(client)
    original_commit = db_session.commit
    raised = False

    def commit_then_report_unique_race() -> None:
        nonlocal raised
        if raised:
            original_commit()
            return
        raised = True
        original_commit()
        raise IntegrityError("simulated concurrent winner", {}, Exception("unique"))

    monkeypatch.setattr(db_session, "commit", commit_then_report_unique_race)
    response = client.post(
        "/api/v1/promotion-invoices/race-replay-invoice/lifecycle-events",
        json={"eventType": "VOIDED", "reason": "系统外已作废", "readVersion": 1},
        headers={"Idempotency-Key": "race-replay-lifecycle-0001"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["lifecycleEvent"]["eventType"] == "VOIDED"


def test_terminated_invoice_is_listed_as_replacement_candidate(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="replacement-candidate-invoice",
        physical_invoice_id="replacement-candidate-physical",
        invoice_number="78345678901234567890",
    )
    _act_as_store(client)
    terminated = client.post(
        "/api/v1/promotion-invoices/replacement-candidate-invoice/lifecycle-events",
        json={"eventType": "VOIDED", "reason": "系统外已作废", "readVersion": 1},
        headers={"Idempotency-Key": "replacement-candidate-void-0001"},
    )
    assert terminated.status_code == 200

    response = client.get(
        "/api/v1/promotion-invoices/replacement-candidates",
        params={"storeId": "store-1"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["list"] == [{
        "invoice": response.json()["data"]["list"][0]["invoice"],
        "lifecycleEvent": response.json()["data"]["list"][0]["lifecycleEvent"],
        "releasedStatementMonths": ["2026-08"],
    }]
    assert response.json()["data"]["list"][0]["invoice"]["invoiceId"] == (
        "replacement-candidate-invoice"
    )


def test_replacement_detail_deduplicates_factory_versions_by_physical_invoice(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="chain-root-invoice",
        physical_invoice_id="chain-root-physical",
        invoice_number="79345678901234567890",
    )
    root = db_session.scalar(
        select(PromotionInvoice).where(PromotionInvoice.invoice_id == "chain-root-invoice")
    )
    root.is_current = False
    db_session.add(
        PromotionInvoiceLifecycleEvent(
            lifecycle_event_id="chain-root-termination",
            physical_invoice_id="chain-root-physical",
            invoice_id="chain-root-invoice",
            invoice_version=1,
            event_type=2,
            reason="系统外已作废",
            read_version=1,
            is_current=True,
            operator_id="store-1-user",
            idempotency_key_hash="chain-root-termination-key",
            request_payload_sha256="chain-root-termination-payload",
            occurred_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
    )
    db_session.add_all([
        PromotionInvoice(
            invoice_id="chain-child-v1", physical_invoice_id="chain-child-physical",
            store_id="store-1", version_no=1, version_kind=1, is_current=False,
            replaces_invoice_id="chain-root-invoice", invoice_number="79345678901234567891",
            invoice_date=date(2026, 8, 21), invoice_amount_cent=1100,
            buyer_name="比亚迪汽车销售有限公司", tax_rate_percent=6,
            invoice_status=2, registered_by="store-1-user",
            registered_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        ),
        PromotionInvoice(
            invoice_id="chain-child-v2", physical_invoice_id="chain-child-physical",
            store_id="store-1", version_no=2, version_kind=2, is_current=True,
            supersedes_invoice_id="chain-child-v1", replaces_invoice_id="chain-root-invoice",
            invoice_number="79345678901234567891", invoice_date=date(2026, 8, 21),
            invoice_amount_cent=1100, buyer_name="比亚迪汽车销售有限公司",
            tax_rate_percent=6, invoice_status=3, registered_by="store-1-user",
            registered_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        ),
        PromotionInvoiceNumberRegistry(
            invoice_number="79345678901234567891",
            physical_invoice_id="chain-child-physical",
            first_invoice_id="chain-child-v1", store_id="store-1",
            registered_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        ),
    ])
    db_session.commit()
    _act_as_store(client)

    detail = client.get("/api/v1/promotion-invoices/chain-root-invoice")

    assert detail.status_code == 200
    assert [item["invoiceId"] for item in detail.json()["data"]["replacements"]] == [
        "chain-child-v1"
    ]
    assert [item["invoiceNumber"] for item in detail.json()["data"]["replacementChain"]] == [
        "79345678901234567890",
        "79345678901234567891",
    ]


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
    order_data = orders.json()["data"]
    assert order_data["total"] == 2
    assert order_data["list"][0]["orderId"] == "order-promotion-current"
    assert order_data["list"][0]["storeName"] == "Store One Historical"
    assert "originalBusinessMonth" not in order_data["list"][0]
    assert "statementPostingMonth" not in order_data["list"][0]

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


def test_store_submits_and_reads_a_direction_scoped_dispute(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    db_session.add(
        SettlementStatementEntry(
            statement_entry_id="entry-dispute-promotion",
            statement_id="statement-1-v2",
            statement_line_id="line-dispute-promotion",
            source_type=1,
            source_record_id="source-dispute-promotion",
            original_fee_result_id="fee-result-dispute-promotion",
            coupon_id="coupon-dispute-promotion",
            order_id="order-dispute-promotion",
            fee_direction=1,
            original_business_month="2026-08",
            statement_posting_month="2026-08",
            base_amount_cent=11000,
            fee_amount_cent=1100,
            rule_version="rule-v1",
            order_status_snapshot="COMPLETED",
            coupon_status_snapshot="USED",
            product_name_snapshot="Frozen Dispute Product",
            sku_id_snapshot="sku-dispute-frozen",
            sku_name_snapshot="Frozen Dispute SKU",
            sale_channel_snapshot="short_video",
            sale_store_id_snapshot="store-sale-frozen",
            sale_store_snapshot="Frozen Sale Store",
            verify_store_id_snapshot="store-verify-frozen",
            verify_store_snapshot="Frozen Verify Store",
            sale_time_snapshot=datetime(2026, 8, 8, tzinfo=timezone.utc),
            verify_time_snapshot=datetime(2026, 8, 9, tzinfo=timezone.utc),
            received_amount_cent_snapshot=11000,
            fee_rate_snapshot=Decimal("0.100000"),
        )
    )
    db_session.commit()

    submitted = client.post(
        "/api/v1/store-settlements/statement-1-v2/disputes",
        json={
            "feeDirection": "PROMOTION",
            "disputeType": "AMOUNT_ERROR",
            "description": "推广服务费金额不一致",
            "contactName": "门店联系人",
            "contactPhone": "13812345678",
            "disputedAmountCent": 100,
            "orders": [
                {
                    "orderId": "order-dispute-promotion",
                    "couponId": "coupon-dispute-promotion",
                    "disputedAmountCent": 100,
                }
            ],
            "evidence": [{"objectKey": "evidence/dispute-001.pdf"}],
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "store-dispute-submit-key-0001"},
    )

    assert submitted.status_code == 200
    assert submitted.json()["data"]["status"] == "PENDING"
    assert submitted.json()["data"]["feeDirection"] == "PROMOTION"
    assert submitted.json()["data"]["contactPhoneMasked"] == "138****5678"
    replay = client.post(
        "/api/v1/store-settlements/statement-1-v2/disputes",
        json={
            "feeDirection": "PROMOTION",
            "disputeType": "AMOUNT_ERROR",
            "description": "推广服务费金额不一致",
            "contactName": "门店联系人",
            "contactPhone": "13812345678",
            "disputedAmountCent": 100,
            "orders": [
                {
                    "orderId": "order-dispute-promotion",
                    "couponId": "coupon-dispute-promotion",
                    "disputedAmountCent": 100,
                }
            ],
            "evidence": [{"objectKey": "evidence/dispute-001.pdf"}],
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "store-dispute-submit-key-0001"},
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["disputeId"] == submitted.json()["data"]["disputeId"]

    statements = client.get(
        "/api/v1/store-settlements",
        params={"storeId": "store-1", "month": "2026-08", "metricScope": "MONTH"},
    )
    assert statements.status_code == 200
    statement = statements.json()["data"]["list"][0]
    assert statement["promotionConfirmableAmountCent"] == 1000
    assert statement["managementConfirmableAmountCent"] == 2200

    promotion_confirmation = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json={
            "feeDirection": "PROMOTION",
            "confirmedAmountCent": statement["promotionConfirmableAmountCent"],
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "store-dispute-promotion-confirm-0001"},
    )
    assert promotion_confirmation.status_code == 200
    assert promotion_confirmation.json()["data"]["confirmedAmountCent"] == 1000
    management_confirmation = client.post(
        "/api/v1/store-settlements/statement-1-v2/confirmations",
        json={
            "feeDirection": "MANAGEMENT",
            "confirmedAmountCent": 2200,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "store-dispute-management-confirm-0001"},
    )
    assert management_confirmation.status_code == 200
    assert management_confirmation.json()["data"]["confirmedAmountCent"] == 2200
    dispute = db_session.scalar(select(SettlementDispute))
    assert dispute is not None
    assert dispute.contact_phone_ciphertext != "13812345678"
    assert db_session.scalar(
        select(FinanceOperationAudit).where(
            FinanceOperationAudit.target_id == dispute.dispute_id,
            FinanceOperationAudit.operation_type == "DISPUTE_SUBMIT",
        )
    ) is not None

    listed = client.get("/api/v1/store-settlements/statement-1-v2/disputes")
    assert listed.status_code == 200
    assert listed.json()["data"]["list"][0]["disputeId"] == submitted.json()["data"]["disputeId"]


def test_store_withdraws_dispute_before_result_without_changing_statement(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    db_session.add(
        SettlementStatementEntry(
            statement_entry_id="entry-dispute-withdraw",
            statement_id="statement-1-v2",
            statement_line_id="line-dispute-withdraw",
            source_type=1,
            source_record_id="source-dispute-withdraw",
            original_fee_result_id="fee-result-dispute-withdraw",
            coupon_id="coupon-dispute-withdraw",
            order_id="order-dispute-withdraw",
            fee_direction=1,
            original_business_month="2026-08",
            statement_posting_month="2026-08",
            base_amount_cent=11000,
            fee_amount_cent=1100,
            rule_version="rule-v1",
        )
    )
    db_session.commit()
    submitted = client.post(
        "/api/v1/store-settlements/statement-1-v2/disputes",
        json={
            "feeDirection": "PROMOTION",
            "disputeType": "AMOUNT_ERROR",
            "description": "申请撤回的异议",
            "contactName": "门店联系人",
            "contactPhone": "13812345678",
            "disputedAmountCent": 100,
            "orders": [
                {
                    "orderId": "order-dispute-withdraw",
                    "couponId": "coupon-dispute-withdraw",
                    "disputedAmountCent": 100,
                }
            ],
            "evidence": [{"objectKey": "evidence/dispute-withdraw.pdf"}],
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "store-dispute-withdraw-key-0001"},
    )
    assert submitted.status_code == 200

    withdrawn = client.post(
        f"/api/v1/disputes/{submitted.json()['data']['disputeId']}/withdrawals",
        json={"reason": "门店确认无需继续处理", "readVersion": 2},
        headers={"Idempotency-Key": "store-dispute-withdraw-key-0002"},
    )

    assert withdrawn.status_code == 200
    assert withdrawn.json()["data"]["status"] == "WITHDRAWN"
    assert withdrawn.json()["data"]["adjustmentReversed"] is False
    current_statement = db_session.scalar(
        select(SettlementStatement).where(
            SettlementStatement.store_id == "store-1",
            SettlementStatement.statement_month == "2026-08",
            SettlementStatement.is_current.is_(True),
        )
    )
    assert current_statement is not None
    assert current_statement.statement_id == "statement-1-v2"
    assert current_statement.version_no == 2


def test_admin_accepts_dispute_by_creating_a_new_immutable_statement_version(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dashboard_routes,
        "utcnow",
        lambda: datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
    )
    _login(client)
    db_session.add_all(
        [
            SettlementStatementLine(
                statement_line_id="line-dispute-accepted",
                statement_id="statement-1-v2",
                fee_direction=1,
                product_scope="LOCAL_LIFE",
                product_type="COUPON",
                original_entry_count=1,
                adjustment_entry_count=1,
                original_base_cent=11000,
                adjustment_base_cent=0,
                net_base_cent=11000,
                original_fee_cent=1100,
                adjustment_fee_cent=0,
                net_fee_cent=1100,
            ),
            SettlementStatementEntry(
                statement_entry_id="entry-dispute-accepted",
                statement_id="statement-1-v2",
                statement_line_id="line-dispute-accepted",
                source_type=1,
                source_record_id="source-dispute-accepted",
                original_fee_result_id="fee-result-dispute-accepted",
                coupon_id="coupon-dispute-accepted",
                order_id="order-dispute-accepted",
                fee_direction=1,
                original_business_month="2026-08",
                statement_posting_month="2026-08",
                product_scope="LOCAL_LIFE",
                product_type="COUPON",
                base_amount_cent=11000,
                fee_amount_cent=1100,
                rule_version="rule-v1",
                order_status_snapshot="COMPLETED",
                product_name_snapshot="Promotion Service",
                sku_id_snapshot="sku-promotion-current",
                sku_name_snapshot="Promotion SKU",
                sale_channel_snapshot="short_video",
                sale_store_snapshot="Store One Historical",
                verify_store_snapshot="Store One Historical",
                sale_time_snapshot=datetime(2026, 8, 8, tzinfo=timezone.utc),
                verify_time_snapshot=datetime(2026, 8, 9, tzinfo=timezone.utc),
                received_amount_cent_snapshot=11000,
                fee_rate_snapshot=0.1,
            ),
            SettlementStatementEntry(
                statement_entry_id="entry-carryforward-dispute-accepted",
                statement_id="statement-1-v2",
                statement_line_id="line-dispute-accepted",
                source_type=2,
                source_record_id="carryforward-adjustment-dispute-v1",
                original_fee_result_id="fee-result-dispute-accepted",
                coupon_id="coupon-dispute-accepted",
                order_id="order-dispute-accepted",
                fee_direction=1,
                original_business_month="2026-08",
                statement_posting_month="2026-08",
                product_scope="LOCAL_LIFE",
                product_type="COUPON",
                base_amount_cent=0,
                fee_amount_cent=0,
                rule_version="rule-v1",
            ),
            SettlementCarryforwardSource(
                carryforward_source_id="carryforward-source-dispute-v1",
                source_event_type=1,
                source_event_key="refund:carryforward-dispute-v1",
                original_fee_result_id="fee-result-dispute-accepted",
                refund_event_id="carryforward-dispute-v1",
                verify_id=None,
                coupon_id="coupon-dispute-accepted",
                order_id="order-dispute-accepted",
                store_id="store-1",
                fee_direction=1,
                original_business_month="2026-08",
                event_month="2026-07",
                adjustment_type=1,
                adjustment_base_cent=0,
                adjustment_fee_cent=0,
                rule_version="rule-v1",
                carryforward_reason="测试账单版本链",
                occurred_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
                created_by="test",
            ),
            SettlementFeeAdjustment(
                adjustment_id="carryforward-adjustment-dispute-v1",
                original_fee_result_id="fee-result-dispute-accepted",
                refund_event_id="carryforward-dispute-v1",
                coupon_id="coupon-dispute-accepted",
                order_id="order-dispute-accepted",
                fee_direction=1,
                original_business_month="2026-08",
                adjustment_posting_month="2026-08",
                adjustment_type=1,
                adjustment_base_cent=0,
                adjustment_fee_cent=0,
                rule_version="rule-v1",
                adjustment_reason="测试账单版本链",
                occurred_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
                created_by="test",
            ),
            SettlementCarryforwardApplication(
                carryforward_application_id="carryforward-application-dispute-v1",
                carryforward_source_id="carryforward-source-dispute-v1",
                target_statement_id="statement-1-v2",
                target_statement_version=2,
                target_adjustment_id="carryforward-adjustment-dispute-v1",
                target_posting_month="2026-08",
                application_version=1,
                is_current=True,
                applied_by="test",
                applied_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            ),
            SettlementStatementConfirmation(
                confirmation_id="confirmation-dispute-accepted-v2",
                statement_id="statement-1-v2",
                fee_direction=1,
                confirmation_status=1,
                confirmed_amount_cent=1100,
                confirmed_by="system-admin",
                idempotency_key_hash="confirmation-dispute-accepted-v2-key",
            ),
        ]
    )
    db_session.commit()
    submitted = client.post(
        "/api/v1/store-settlements/statement-1-v2/disputes",
        json={
            "feeDirection": "PROMOTION",
            "disputeType": "AMOUNT_ERROR",
            "description": "推广服务费多收 1 元",
            "contactName": "门店联系人",
            "contactPhone": "13812345678",
            "disputedAmountCent": 100,
            "orders": [
                {
                    "orderId": "order-dispute-accepted",
                    "couponId": "coupon-dispute-accepted",
                    "disputedAmountCent": 100,
                }
            ],
            "evidence": [{"objectKey": "evidence/dispute-accepted.pdf"}],
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "store-dispute-accepted-key-0001"},
    )
    assert submitted.status_code == 200
    dispute_id = submitted.json()["data"]["disputeId"]

    listed = client.get(
        "/api/v1/admin/disputes",
        params={
            "storeId": "store-1",
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "status": "PENDING",
            "disputeType": "AMOUNT_ERROR",
        },
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    assert listed.json()["data"]["list"][0]["disputeId"] == dispute_id

    for index, target_status in enumerate(
        ("IN_REVIEW", "PENDING_ADMIN_APPROVAL"), start=2
    ):
        transitioned = client.post(
            f"/api/v1/admin/disputes/{dispute_id}/transitions",
            json={
                "targetStatus": target_status,
                "resolutionNote": f"内部处理步骤 {index}",
                "readVersion": 2,
            },
            headers={"Idempotency-Key": f"admin-dispute-transition-key-000{index}"},
        )
        assert transitioned.status_code == 200
        assert transitioned.json()["data"]["status"] == target_status

    accepted = client.post(
        f"/api/v1/admin/disputes/{dispute_id}/transitions",
        json={
            "targetStatus": "ACCEPTED_WITH_ADJUSTMENT",
            "resolutionNote": "确认多收，调减 1 元",
            "adjustmentAmountCent": -100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "admin-dispute-transition-key-0004"},
    )
    replayed = client.post(
        f"/api/v1/admin/disputes/{dispute_id}/transitions",
        json={
            "targetStatus": "ACCEPTED_WITH_ADJUSTMENT",
            "resolutionNote": "确认多收，调减 1 元",
            "adjustmentAmountCent": -100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "admin-dispute-transition-key-0004"},
    )

    assert accepted.status_code == 200
    assert replayed.status_code == 200
    assert replayed.json()["data"] == accepted.json()["data"]
    assert accepted.json()["data"]["status"] == "ACCEPTED_WITH_ADJUSTMENT"
    assert accepted.json()["data"]["previousStatementId"] == "statement-1-v2"
    assert accepted.json()["data"]["previousVersion"] == 2
    assert accepted.json()["data"]["currentVersion"] == 3
    current_statement_id = accepted.json()["data"]["currentStatementId"]

    accepted_replay = client.post(
        f"/api/v1/admin/disputes/{dispute_id}/transitions",
        json={
            "targetStatus": "ACCEPTED_WITH_ADJUSTMENT",
            "resolutionNote": "确认多收，调减 1 元",
            "adjustmentAmountCent": -100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "admin-dispute-transition-key-0004"},
    )
    assert accepted_replay.status_code == 200
    assert accepted_replay.json()["data"]["currentStatementId"] == current_statement_id

    stale_competitor = client.post(
        f"/api/v1/admin/disputes/{dispute_id}/transitions",
        json={
            "targetStatus": "ACCEPTED_WITH_ADJUSTMENT",
            "resolutionNote": "重复处理旧版本",
            "adjustmentAmountCent": -100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "admin-dispute-transition-stale-0001"},
    )
    assert stale_competitor.status_code == 409

    statements = list(
        db_session.scalars(
            select(SettlementStatement)
            .where(
                SettlementStatement.store_id == "store-1",
                SettlementStatement.statement_month == "2026-08",
            )
            .order_by(SettlementStatement.version_no)
        )
    )
    assert [statement.version_no for statement in statements] == [1, 2, 3]
    assert statements[1].is_current is False
    assert statements[2].is_current is True
    assert statements[2].supersedes_statement_id == "statement-1-v2"
    assert statements[2].promotion_original_fee_cent == 1100
    assert statements[2].promotion_adjustment_fee_cent == -100
    assert statements[2].promotion_net_fee_cent == 1000

    new_entries = list(
        db_session.scalars(
            select(SettlementStatementEntry).where(
                SettlementStatementEntry.statement_id == current_statement_id
            )
        )
    )
    assert len(new_entries) == 3
    assert sum(entry.fee_amount_cent for entry in new_entries) == 1000
    assert {entry.source_type for entry in new_entries} == {1, 2}
    applications = list(
        db_session.scalars(
            select(SettlementCarryforwardApplication)
            .where(
                SettlementCarryforwardApplication.carryforward_source_id
                == "carryforward-source-dispute-v1"
            )
            .order_by(SettlementCarryforwardApplication.application_version)
        )
    )
    assert [row.application_version for row in applications] == [1, 2]
    assert [row.is_current for row in applications] == [False, True]
    assert applications[1].target_statement_id == current_statement_id
    assert applications[1].target_statement_version == 3
    assert applications[1].target_adjustment_id != applications[0].target_adjustment_id
    assert applications[1].target_adjustment_id in {
        row.source_record_id for row in new_entries
    }
    assert applications[0].target_adjustment_id not in {
        row.source_record_id for row in new_entries
    }
    assert db_session.scalar(
        select(SettlementFeeAdjustment).where(
            SettlementFeeAdjustment.adjustment_id
            == applications[1].target_adjustment_id
        )
    ) is not None
    assert db_session.scalar(
        select(SettlementStatementConfirmation).where(
            SettlementStatementConfirmation.confirmation_id
            == "confirmation-dispute-accepted-v2"
        )
    ) is not None
    new_confirmation = db_session.scalar(
        select(SettlementStatementConfirmation).where(
            SettlementStatementConfirmation.statement_id == current_statement_id,
            SettlementStatementConfirmation.fee_direction == 1,
        )
    )
    assert new_confirmation is not None
    assert new_confirmation.confirmed_amount_cent == 1000
    assert new_confirmation.confirmed_by == "system:auto-confirmation"
    dispute = db_session.scalar(
        select(SettlementDispute).where(SettlementDispute.dispute_id == dispute_id)
    )
    assert dispute is not None
    assert dispute.result_statement_id == current_statement_id
    assert db_session.scalar(
        select(FinanceOperationAudit).where(
            FinanceOperationAudit.target_id == dispute_id,
            FinanceOperationAudit.operation_type == "DISPUTE_TRANSITION",
        )
    ) is not None

    withdrawn_after_result = client.post(
        f"/api/v1/disputes/{dispute_id}/withdrawals",
        json={"reason": "结果后撤回，仅保留记录", "readVersion": 3},
        headers={"Idempotency-Key": "store-dispute-result-withdraw-key-0001"},
    )
    assert withdrawn_after_result.status_code == 200
    assert withdrawn_after_result.json()["data"]["status"] == "WITHDRAWN"
    assert withdrawn_after_result.json()["data"]["adjustmentReversed"] is False
    db_session.expire_all()
    current_after_withdrawal = db_session.scalar(
        select(SettlementStatement).where(
            SettlementStatement.store_id == "store-1",
            SettlementStatement.statement_month == "2026-08",
            SettlementStatement.is_current.is_(True),
        )
    )
    assert current_after_withdrawal is not None
    assert current_after_withdrawal.statement_id == current_statement_id
    assert current_after_withdrawal.promotion_net_fee_cent == 1000


def test_admin_rejects_dispute_without_creating_a_statement_version(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    db_session.add(
        SettlementDispute(
            dispute_id="dispute-rejected",
            statement_id="statement-1-v2",
            store_id="store-1",
            statement_month="2026-08",
            fee_direction=2,
            dispute_type=4,
            status=1,
            disputed_amount_cent=50,
            description="管理服务费异议",
            contact_name="门店联系人",
            contact_phone_ciphertext="invalid-test-ciphertext",
            evidence_json=[{"objectKey": "evidence/dispute-rejected.pdf"}],
            submitted_by="store-user",
        )
    )
    db_session.commit()

    rejected = client.post(
        "/api/v1/admin/disputes/dispute-rejected/transitions",
        json={
            "targetStatus": "REJECTED",
            "resolutionNote": "核对后金额无误",
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "admin-dispute-rejected-key-0001"},
    )

    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "REJECTED"
    assert rejected.json()["data"]["resultStatementId"] is None
    assert db_session.scalar(
        select(func.count()).select_from(SettlementStatement).where(
            SettlementStatement.store_id == "store-1",
            SettlementStatement.statement_month == "2026-08",
        )
    ) == 2


def test_finance_import_collects_all_csv_errors_without_business_writes(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    csv_body = (
        "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n"
        "bad-number,UNKNOWN,,bad-date,-1\n"
        "12345678901234567890,APPROVED_SETTLED,,bad-date,not-an-integer\n"
    ).encode("utf-8")

    response = client.post(
        "/api/v1/admin/finance-imports",
        data={
            "importType": "PROMOTION_FACTORY_RESULT",
            "statementMonth": "2026-08",
        },
        files={"file": ("promotion-review.csv", csv_body, "text/csv")},
        headers={"Idempotency-Key": "finance-import-validation-key-0001"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scenario"] == "BATCH_VALIDATION_FAILED"
    assert data["totalRows"] == 2
    assert data["errorRows"] == 2
    assert len(data["errors"]["list"]) >= 4
    batch = db_session.scalar(select(FinanceImportBatch))
    assert batch is not None
    assert batch.batch_status == 6
    rows = list(db_session.scalars(select(FinanceImportRow).order_by(FinanceImportRow.row_number)))
    assert len(rows) == 2
    assert all(row.validation_errors for row in rows)
    assert all(row.row_status == 4 for row in rows)
    assert db_session.scalar(select(func.count()).select_from(PromotionInvoice)) == 0
    assert db_session.scalar(select(func.count()).select_from(InvoiceRecord)) == 0

    listed = client.get(
        "/api/v1/admin/finance-imports",
        params={
            "importType": "PROMOTION_FACTORY_RESULT",
            "statementMonth": "2026-08",
            "page": 1,
            "pageSize": 10,
        },
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    assert listed.json()["data"]["list"][0]["batchId"] == data["batchId"]

    detail = client.get(
        f"/api/v1/admin/finance-imports/{data['batchId']}",
        params={"errorPage": 1, "errorPageSize": 1},
    )
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["scenario"] == "BATCH_VALIDATION_FAILED"
    assert detail_data["errors"]["total"] >= 4
    assert detail_data["errors"]["page"] == 1
    assert detail_data["errors"]["pageSize"] == 1
    assert {item["rowNumber"] for item in detail_data["errors"]["list"]} == {2}

    downloaded = client.get(
        f"/api/v1/admin/finance-imports/{data['batchId']}/error-file"
    )
    assert downloaded.status_code == 200
    assert "text/csv" in downloaded.headers["content-type"]
    csv_text = downloaded.content.decode("utf-8-sig")
    assert csv_text.startswith(
        "rowNumber,businessKey,field,originalValue,reason,suggestion"
    )
    assert len(csv_text.strip().splitlines()) == detail_data["errors"]["total"] + 1


def test_finance_import_commit_creates_promotion_invoice_version(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    invoice_number = "22345678901234567890"
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="promotion-import-v1",
        physical_invoice_id="promotion-import-physical",
        invoice_number=invoice_number,
    )

    uploaded = client.post(
        "/api/v1/admin/finance-imports",
        data={
            "importType": "PROMOTION_FACTORY_RESULT",
            "statementMonth": "2026-08",
        },
        files={
            "file": (
                "promotion-review.csv",
                (
                    "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n"
                    f"{invoice_number},APPROVED_SETTLED,,2026-08-21,1100\n"
                ).encode("utf-8"),
                "text/csv",
            )
        },
        headers={"Idempotency-Key": "finance-import-upload-key-0001"},
    )
    assert uploaded.status_code == 200
    preview = uploaded.json()["data"]
    assert preview["scenario"] == "FIRST_IMPORT_READY"
    assert preview["readVersion"] == 0

    committed = client.post(
        f"/api/v1/admin/finance-imports/{preview['batchId']}/commits",
        json={"readVersion": 0, "changeReason": "外部审核结果首次导入"},
        headers={"Idempotency-Key": "finance-import-commit-key-0001"},
    )

    assert committed.status_code == 200
    result = committed.json()["data"]
    assert result["batchId"] == preview["batchId"]
    assert result["status"] == "COMMITTED"
    assert result["currentVersion"] == 1

    db_session.expire_all()
    old_invoice = db_session.scalar(
        select(PromotionInvoice).where(
            PromotionInvoice.invoice_id == "promotion-import-v1"
        )
    )
    current_invoice = db_session.scalar(
        select(PromotionInvoice).where(
            PromotionInvoice.store_id == "store-1",
            PromotionInvoice.invoice_number == invoice_number,
            PromotionInvoice.is_current.is_(True),
        )
    )
    assert old_invoice is not None
    assert old_invoice.is_current is False
    assert current_invoice is not None
    assert current_invoice.invoice_id != old_invoice.invoice_id
    assert current_invoice.version_no == 2
    assert current_invoice.supersedes_invoice_id == old_invoice.invoice_id
    assert current_invoice.invoice_status == 3
    current_allocation = db_session.scalar(
        select(PromotionInvoiceAllocation).where(
            PromotionInvoiceAllocation.store_id == "store-1",
            PromotionInvoiceAllocation.statement_month == "2026-08",
            PromotionInvoiceAllocation.is_current.is_(True),
        )
    )
    assert current_allocation is not None
    assert current_allocation.invoice_id == current_invoice.invoice_id
    batch = db_session.scalar(
        select(FinanceImportBatch).where(
            FinanceImportBatch.batch_id == preview["batchId"]
        )
    )
    assert batch is not None
    assert batch.batch_status == 5
    assert batch.current_version == 1
    row = db_session.scalar(
        select(FinanceImportRow).where(
            FinanceImportRow.batch_id == preview["batchId"]
        )
    )
    assert row is not None
    assert row.row_status == 5
    assert row.target_record_id == current_invoice.invoice_id


def test_finance_import_detects_no_change_and_difference(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    invoice_number = "32345678901234567890"
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="promotion-diff-v1",
        physical_invoice_id="promotion-diff-physical",
        invoice_number=invoice_number,
    )

    def upload(status_name: str, idempotency_key: str):
        return client.post(
            "/api/v1/admin/finance-imports",
            data={
                "importType": "PROMOTION_FACTORY_RESULT",
                "statementMonth": "2026-08",
            },
            files={
                "file": (
                    "promotion-review.csv",
                    (
                        "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n"
                        + (
                            f"{invoice_number},APPROVED_SETTLED,,2026-08-21,1100\n"
                            if status_name == "APPROVED_SETTLED"
                            else f"{invoice_number},REJECTED_REUPLOAD,厂家退回,,\n"
                        )
                    ).encode("utf-8"),
                    "text/csv",
                )
            },
            headers={"Idempotency-Key": idempotency_key},
        )

    first = upload("APPROVED_SETTLED", "finance-import-first-upload-key-0001")
    assert first.status_code == 200
    first_data = first.json()["data"]
    assert first_data["scenario"] == "FIRST_IMPORT_READY"
    committed = client.post(
        f"/api/v1/admin/finance-imports/{first_data['batchId']}/commits",
        json={"readVersion": 0, "changeReason": "首次导入"},
        headers={"Idempotency-Key": "finance-import-first-commit-key-0001"},
    )
    assert committed.status_code == 200

    unchanged = upload("APPROVED_SETTLED", "finance-import-no-change-key-0001")
    assert unchanged.status_code == 200
    unchanged_data = unchanged.json()["data"]
    assert unchanged_data["scenario"] == "NO_CHANGE"
    assert unchanged_data["readVersion"] == 1
    assert unchanged_data["currentVersion"] == 1
    assert unchanged_data["contentChanged"] is False

    changed = upload("REJECTED_REUPLOAD", "finance-import-diff-key-0001")
    assert changed.status_code == 200
    changed_data = changed.json()["data"]
    assert changed_data["scenario"] == "DIFF_CONFIRMATION_REQUIRED"
    assert changed_data["readVersion"] == 1
    assert changed_data["currentVersion"] == 1
    assert changed_data["contentChanged"] is True
    assert db_session.scalar(
        select(func.count()).select_from(PromotionInvoice).where(
            PromotionInvoice.invoice_number == invoice_number
        )
    ) == 2


def test_finance_import_correction_rejects_stale_competing_preview(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    invoice_number = "42345678901234567890"
    _seed_current_promotion_invoice(
        db_session,
        invoice_id="promotion-conflict-v1",
        physical_invoice_id="promotion-conflict-physical",
        invoice_number=invoice_number,
    )

    def upload(status_name: str, idempotency_key: str) -> dict:
        response = client.post(
            "/api/v1/admin/finance-imports",
            data={
                "importType": "PROMOTION_FACTORY_RESULT",
                "statementMonth": "2026-08",
            },
            files={
                "file": (
                    "promotion-review.csv",
                    (
                        "invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent\n"
                        + (
                            f"{invoice_number},APPROVED_SETTLED,,2026-08-21,1100\n"
                            if status_name == "APPROVED_SETTLED"
                            else f"{invoice_number},REJECTED_REUPLOAD,厂家退回,,\n"
                        )
                    ).encode("utf-8"),
                    "text/csv",
                )
            },
            headers={"Idempotency-Key": idempotency_key},
        )
        assert response.status_code == 200
        return response.json()["data"]

    initial = upload("APPROVED_SETTLED", "finance-conflict-upload-initial-0001")
    committed = client.post(
        f"/api/v1/admin/finance-imports/{initial['batchId']}/commits",
        json={"readVersion": 0, "changeReason": "首次导入"},
        headers={"Idempotency-Key": "finance-conflict-commit-initial-0001"},
    )
    assert committed.status_code == 200

    winner = upload("REJECTED_REUPLOAD", "finance-conflict-upload-winner-0001")
    stale = upload("REJECTED_REUPLOAD", "finance-conflict-upload-stale-0001")
    assert winner["scenario"] == stale["scenario"] == "DIFF_CONFIRMATION_REQUIRED"
    corrected = client.post(
        f"/api/v1/admin/finance-imports/{winner['batchId']}/corrections",
        json={"readVersion": 1, "changeReason": "外部结果更正"},
        headers={"Idempotency-Key": "finance-conflict-correction-winner-0001"},
    )
    assert corrected.status_code == 200
    corrected_data = corrected.json()["data"]
    assert corrected_data["status"] == "CORRECTED"
    assert corrected_data["currentVersion"] == 2

    rejected = client.post(
        f"/api/v1/admin/finance-imports/{stale['batchId']}/commits",
        json={"readVersion": 1, "changeReason": "过期预览提交"},
        headers={"Idempotency-Key": "finance-conflict-commit-stale-0001"},
    )
    assert rejected.status_code == 409
    conflict_detail = rejected.json()["detail"]
    assert conflict_detail["code"] == "VERSION_CONFLICT"
    assert conflict_detail["data"]["readVersion"] == 1
    assert conflict_detail["data"]["currentVersion"] == 2
    assert conflict_detail["data"]["latestOperator"] == "system-admin"
    assert conflict_detail["data"]["latestOperatedAt"] is not None
    db_session.expire_all()
    stale_batch = db_session.scalar(
        select(FinanceImportBatch).where(
            FinanceImportBatch.batch_id == stale["batchId"]
        )
    )
    assert stale_batch is not None
    assert stale_batch.batch_status == 7
    assert stale_batch.current_version == 2
    current_invoice = db_session.scalar(
        select(PromotionInvoice).where(
            PromotionInvoice.invoice_number == invoice_number,
            PromotionInvoice.is_current.is_(True),
        )
    )
    assert current_invoice is not None
    assert current_invoice.version_no == 3
    assert current_invoice.invoice_status == 4


def test_management_invoice_xlsx_and_factory_deduction_are_versioned_in_full(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    invoice_number = "52345678901234567890"
    db_session.add(
        SettlementStatementConfirmation(
            confirmation_id="management-import-confirmation",
            statement_id="statement-1-v2",
            fee_direction=2,
            confirmed_amount_cent=2200,
            confirmation_status=1,
            confirmed_by="store-user",
            confirmed_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet()
    sheet.append(
        [
            "storeId",
            "statementMonth",
            "storeName",
            "invoiceNumber",
            "invoiceDate",
            "deductionDate",
            "deductionAmountCent",
        ]
    )
    sheet.append(
        [
            "store-1",
            "2026-08",
            "Store One",
            invoice_number,
            "2026-08-15",
            "2026-08-21",
            2200,
        ]
    )
    xlsx_file = BytesIO()
    workbook.save(xlsx_file)

    uploaded = client.post(
        "/api/v1/admin/finance-imports",
        data={
            "importType": "MANAGEMENT_FACTORY_RESULT",
            "statementMonth": "2026-08",
        },
        files={
            "file": (
                "management-invoice.xlsx",
                xlsx_file.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers={"Idempotency-Key": "management-xlsx-upload-key-0001"},
    )
    assert uploaded.status_code == 200
    preview = uploaded.json()["data"]
    assert preview["scenario"] == "FIRST_IMPORT_READY"
    committed = client.post(
        f"/api/v1/admin/finance-imports/{preview['batchId']}/commits",
        json={"readVersion": 0, "changeReason": "管理服务费发票明细导入"},
        headers={"Idempotency-Key": "management-xlsx-commit-key-0001"},
    )
    assert committed.status_code == 200
    db_session.expire_all()
    management_invoice = db_session.scalar(
        select(InvoiceRecord).where(
            InvoiceRecord.store_id == "store-1",
            InvoiceRecord.statement_month == "2026-08",
            InvoiceRecord.is_current.is_(True),
        )
    )
    management_batch = db_session.scalar(
        select(FinanceImportBatch).where(
            FinanceImportBatch.batch_id == preview["batchId"]
        )
    )
    assert management_invoice is not None
    assert management_batch is not None
    assert management_invoice.version_no == 1
    assert management_invoice.invoice_number == invoice_number
    assert management_invoice.invoice_amount_cent == 2200
    assert management_invoice.invoice_status == 3
    assert management_invoice.registered_at == management_batch.committed_at
    assert management_invoice.factory_deduction_date == date(2026, 8, 21)
    assert management_invoice.factory_deduction_amount_cent == 2200


def test_legacy_split_promotion_settlement_template_is_rejected(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    invoice_number = "62345678901234567890"
    db_session.add_all(
        [
            PromotionInvoice(
                invoice_id="promotion-settlement-v1",
                store_id="store-1",
                version_no=1,
                is_current=True,
                invoice_number=invoice_number,
                invoice_date=date(2026, 8, 10),
                invoice_amount_cent=1100,
                buyer_name="比亚迪汽车销售有限公司",
                tax_rate_percent=6,
                invoice_status=2,
                registered_by="store-user",
                registered_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            ),
            PromotionInvoiceAllocation(
                allocation_id="promotion-settlement-allocation-v1",
                invoice_id="promotion-settlement-v1",
                store_id="store-1",
                statement_id="statement-1-v2",
                statement_month="2026-08",
                settlement_batch_month="2026-07",
                allocated_amount_cent=1100,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    uploaded = client.post(
        "/api/v1/admin/finance-imports",
        data={
            "importType": "PROMOTION_SETTLEMENT_RESULT",
            "statementMonth": "2026-08",
        },
        files={
            "file": (
                "promotion-settlement.csv",
                (
                    "storeId,invoiceNumber,amountCent\n"
                    f"store-1,{invoice_number},1100\n"
                ).encode("utf-8"),
                "text/csv",
            )
        },
        headers={"Idempotency-Key": "promotion-settlement-upload-key-0001"},
    )
    assert uploaded.status_code == 422
    assert uploaded.json()["detail"]["code"] == "VALIDATION_FAILED"


def test_finance_import_rejects_more_than_five_thousand_rows(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    csv_body = (
        "storeId,storeName,sapCode,importedAt\n"
        + "".join(
            f"missing-{row_number},Wrong Store,SAP-X,not-a-date\n"
            for row_number in range(5001)
        )
    ).encode("utf-8")

    response = client.post(
        "/api/v1/admin/finance-imports",
        data={
            "importType": "BASIC_INFO",
            "statementMonth": "2026-08",
        },
        files={"file": ("too-many-rows.csv", csv_body, "text/csv")},
        headers={"Idempotency-Key": "finance-import-row-limit-key-0001"},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "IMPORT_FILE_TOO_LARGE"
    assert db_session.scalar(select(func.count()).select_from(FinanceImportBatch)) == 0
    assert db_session.scalar(select(func.count()).select_from(FinanceImportRow)) == 0


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
                buyer_name="比亚迪汽车销售有限公司",
                tax_rate_percent=6,
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
                settlement_batch_month="2026-09",
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
                order_status_snapshot="PAID",
                coupon_status_snapshot="USED",
                product_name_snapshot="Promotion Product",
                sku_id_snapshot="sku-promotion-current",
                sku_name_snapshot="Promotion SKU",
                sale_channel_snapshot="short_video",
                sale_store_id_snapshot="store-1",
                sale_store_snapshot="Store One Historical",
                verify_store_id_snapshot="store-1",
                verify_store_snapshot="Store One Historical",
                sale_time_snapshot=datetime(2026, 8, 10, 8, tzinfo=timezone.utc),
                verify_time_snapshot=datetime(2026, 8, 20, 9, tzinfo=timezone.utc),
                received_amount_cent_snapshot=11000,
                fee_rate_snapshot=Decimal("0.100000"),
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
                order_status_snapshot="PAID",
                coupon_status_snapshot="USED",
                product_name_snapshot="Management Product",
                sku_id_snapshot="sku-management-current",
                sku_name_snapshot="Management SKU",
                sale_channel_snapshot="live",
                sale_store_id_snapshot="store-1",
                sale_store_snapshot="Store One Historical",
                verify_store_id_snapshot="store-1",
                verify_store_snapshot="Store One Historical",
                sale_time_snapshot=datetime(2026, 8, 11, 8, tzinfo=timezone.utc),
                verify_time_snapshot=datetime(2026, 8, 21, 9, tzinfo=timezone.utc),
                received_amount_cent_snapshot=11000,
                fee_rate_snapshot=Decimal("0.200000"),
            ),
        ]
    )
    db_session.flush()
    promotion_order = RawDouyinOrder(
        order_id="order-promotion-current",
        order_status="PAID",
        order_status_raw="PAID",
        order_status_normalized="PAID",
        sku_id="sku-promotion-current",
        product_name="Promotion Product",
        sale_time=datetime(2026, 8, 10, 8, tzinfo=timezone.utc),
        paid_amount_cent=11000,
        order_paid_amount_cent=11000,
        sale_channel="short_video",
        sale_channel_raw="short_video",
        sale_channel_normalized="SHORT_VIDEO",
    )
    management_order = RawDouyinOrder(
        order_id="order-management-current",
        order_status="PAID",
        order_status_raw="PAID",
        order_status_normalized="PAID",
        sku_id="sku-management-current",
        product_name="Management Product",
        sale_time=datetime(2026, 8, 11, 8, tzinfo=timezone.utc),
        paid_amount_cent=11000,
        order_paid_amount_cent=11000,
        sale_channel="live",
        sale_channel_raw="live",
        sale_channel_normalized="LIVE",
    )
    db_session.add_all([promotion_order, management_order])
    db_session.flush()
    db_session.add_all(
        [
            RawDouyinOrderCoupon(
                coupon_id="coupon-promotion-current",
                order_id=promotion_order.order_id,
                raw_order_id=promotion_order.id,
                coupon_status="USED",
                coupon_status_raw="USED",
                coupon_status_normalized="USED",
                coupon_paid_amount_cent=11000,
                coupon_refunded_amount_cent=2000,
                latest_refund_at=datetime(2026, 8, 25, 10, tzinfo=timezone.utc),
            ),
            RawDouyinOrderCoupon(
                coupon_id="coupon-management-current",
                order_id=management_order.order_id,
                raw_order_id=management_order.id,
                coupon_status="USED",
                coupon_status_raw="USED",
                coupon_status_normalized="USED",
                coupon_paid_amount_cent=11000,
                coupon_refunded_amount_cent=0,
            ),
            RawDouyinVerifyRecord(
                verify_id="verify-promotion-current",
                coupon_id="coupon-promotion-current",
                verify_status="VERIFIED",
                verify_time=datetime(2026, 8, 20, 9, tzinfo=timezone.utc),
                sku_id="sku-promotion-current",
                product_name="Promotion Product",
                paid_amount_cent=11000,
            ),
            RawDouyinVerifyRecord(
                verify_id="verify-management-current",
                coupon_id="coupon-management-current",
                verify_status="VERIFIED",
                verify_time=datetime(2026, 8, 21, 9, tzinfo=timezone.utc),
                sku_id="sku-management-current",
                product_name="Management Product",
                paid_amount_cent=11000,
            ),
            DimSkuProductRule(
                sku_id="sku-promotion-current",
                sku_name="Promotion SKU",
                product_name="Promotion Product",
                product_scope="all",
                product_type="service",
            ),
            DimSkuProductRule(
                sku_id="sku-management-current",
                sku_name="Management SKU",
                product_name="Management Product",
                product_scope="all",
                product_type="service",
            ),
            SettlementFeeResult(
                fee_result_id="fee-result-promotion-current",
                coupon_id="coupon-promotion-current",
                order_id="order-promotion-current",
                fee_direction=1,
                result_version=1,
                original_business_month="2026-08",
                rule_match_date=date(2026, 8, 10),
                sale_store_id="store-1",
                verify_store_id="store-1",
                sku_id="sku-promotion-current",
                product_scope="all",
                product_type="service",
                sale_channel_normalized="SHORT_VIDEO",
                source_amount_cent=11000,
                refunded_amount_cent=2000,
                fee_base_cent=11000,
                fee_rate=Decimal("0.100000"),
                fee_amount_cent=1100,
                rule_version="rule-v1",
                scope_rule_version="scope-v1",
                result_status=1,
                calculation_run_id="finance-g3",
                calculated_at=datetime(2026, 8, 20, 9, tzinfo=timezone.utc),
            ),
            SettlementFeeResult(
                fee_result_id="fee-result-management-current",
                coupon_id="coupon-management-current",
                order_id="order-management-current",
                fee_direction=2,
                result_version=1,
                original_business_month="2026-08",
                rule_match_date=date(2026, 8, 21),
                sale_store_id="store-1",
                verify_store_id="store-1",
                sku_id="sku-management-current",
                product_scope="all",
                product_type="service",
                sale_channel_normalized="LIVE",
                source_amount_cent=11000,
                refunded_amount_cent=0,
                fee_base_cent=11000,
                fee_rate=Decimal("0.200000"),
                fee_amount_cent=2200,
                rule_version="rule-v1",
                scope_rule_version="scope-v1",
                result_status=1,
                calculation_run_id="finance-g3",
                calculated_at=datetime(2026, 8, 21, 9, tzinfo=timezone.utc),
            ),
            SettlementFeeAdjustment(
                adjustment_id="adjustment-promotion-refund",
                original_fee_result_id="fee-result-promotion-current",
                refund_event_id="refund-promotion-current",
                coupon_id="coupon-promotion-current",
                order_id="order-promotion-current",
                fee_direction=1,
                original_business_month="2026-08",
                adjustment_posting_month="2026-08",
                adjustment_type=1,
                adjustment_base_cent=-2000,
                adjustment_fee_cent=-200,
                rule_version="rule-v1",
                adjustment_reason="partial refund",
                occurred_at=datetime(2026, 8, 25, 10, tzinfo=timezone.utc),
                created_by="finance-g3",
            ),
            SettlementStatementEntry(
                statement_entry_id="entry-promotion-refund",
                statement_id="statement-1-v2",
                statement_line_id="line-promotion-current",
                source_type=2,
                source_record_id="adjustment-promotion-refund",
                original_fee_result_id="fee-result-promotion-current",
                coupon_id="coupon-promotion-current",
                order_id="order-promotion-current",
                fee_direction=1,
                original_business_month="2026-08",
                statement_posting_month="2026-08",
                base_amount_cent=-2000,
                fee_amount_cent=-200,
                rule_version="rule-v1",
                order_status_snapshot="PAID",
                coupon_status_snapshot="USED",
                product_name_snapshot="Promotion Product",
                sku_id_snapshot="sku-promotion-current",
                sku_name_snapshot="Promotion SKU",
                sale_channel_snapshot="short_video",
                sale_store_id_snapshot="store-1",
                sale_store_snapshot="Store One Historical",
                verify_store_id_snapshot="store-1",
                verify_store_snapshot="Store One Historical",
                sale_time_snapshot=datetime(2026, 8, 10, 8, tzinfo=timezone.utc),
                verify_time_snapshot=datetime(2026, 8, 20, 9, tzinfo=timezone.utc),
                received_amount_cent_snapshot=11000,
                fee_rate_snapshot=Decimal("0.100000"),
                refund_at_snapshot=datetime(2026, 8, 25, 10, tzinfo=timezone.utc),
                adjustment_type_snapshot=1,
            ),
            InvoiceStatusEvent(
                event_id="promotion-settled-event",
                invoice_id="promotion-invoice-current",
                event_type=3,
                from_status=2,
                to_status=3,
                operator_id="system-admin",
                business_date=date(2026, 10, 5),
                business_amount_cent=1100,
                occurred_at=datetime(2026, 10, 5, 1, tzinfo=timezone.utc),
            ),
        ]
    )
    management_invoice = db_session.scalar(
        select(InvoiceRecord).where(
            InvoiceRecord.invoice_id == "management-invoice-current"
        )
    )
    assert management_invoice is not None
    management_invoice.factory_deduction_date = date(2026, 10, 5)
    management_invoice.factory_deduction_amount_cent = 2200
    db_session.commit()


def test_admin_finance_queries_and_order_export_share_scope(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    _seed_finance_query_facts(db_session)

    promotion_summary = client.get(
        "/api/v1/admin/finance/summary",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )
    assert promotion_summary.status_code == 200
    assert promotion_summary.json()["data"]["metrics"] == {
        "statementTotalCent": 2000,
        "confirmedAmountCent": 0,
        "pendingInvoiceAmountCent": 0,
        "issuedAmountCent": 1100,
        "settledOrDeductedAmountCent": 1100,
    }

    management_invoices = client.get(
        "/api/v1/admin/finance/invoices",
        params={
            "month": "2026-08",
            "feeDirection": "MANAGEMENT",
            "invoiceStatus": "APPROVED_SETTLED",
        },
    )
    assert management_invoices.status_code == 200
    assert management_invoices.json()["data"]["list"][0]["invoiceId"] == "management-invoice-current"

    details = client.get(
        "/api/v1/admin/finance/order-details",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "storeId": "store-1",
        },
    )
    assert details.status_code == 200
    assert details.json()["data"]["total"] == 2
    assert details.json()["data"]["list"][0]["orderId"] == "order-promotion-current"

    stores = client.get(
        "/api/v1/admin/finance/stores",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
            "q": "Store One",
        },
    )
    assert stores.status_code == 200
    assert stores.json()["data"]["list"][0]["storeId"] == "store-1"
    assert stores.json()["data"]["list"][0]["sapCode"] is None

    export = client.get(
        "/api/v1/admin/finance/order-details/export",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "storeId": "store-1",
        },
    )
    assert export.status_code == 200
    assert export.content.startswith(b"\xef\xbb\xbf")
    assert export.headers["content-type"].startswith("text/csv")
    assert export.headers["x-export-filters"] == '{"feeDirection":"PROMOTION","month":"2026-08","storeId":"store-1"}'
    assert "order-promotion-current" in export.content.decode("utf-8-sig")


def test_admin_finance_order_details_use_one_complete_projection_for_list_and_export(
    client: TestClient, db_session: Session
) -> None:
    """List and export must share the complete, server-side finance projection."""
    _login(client)
    _seed_finance_query_facts(db_session)

    listed = client.get(
        "/api/v1/admin/finance/order-details",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "storeId": "store-1",
            "sapCode": "SAP-STORE-ONE-HIST",
            "invoiceNumber": "12345678901234567890",
            "orderId": "order-promotion-current",
            "skuId": "sku-promotion-current",
            "saleChannel": "short_video",
            "invoiceStatus": "APPROVED_SETTLED",
            "submittedFrom": "2026-10-05T00:00:00+00:00",
            "submittedTo": "2026-10-06T00:00:00+00:00",
            "verifyFrom": "2026-08-01T00:00:00+00:00",
            "verifyTo": "2026-08-31T23:59:59+00:00",
            "page": 1,
            "pageSize": 1,
        },
    )

    assert listed.status_code == 200
    payload = listed.json()["data"]
    assert payload["total"] == 2
    assert payload["page"] == 1
    assert payload["pageSize"] == 1
    row = payload["list"][0]
    assert {
        "statementEntryId", "statementId", "storeId", "storeName", "sapCode",
        "statementMonth", "feeDirection", "orderId", "couponId", "orderStatus",
        "couponStatus", "productName", "skuId", "skuName", "saleChannel",
        "saleStoreId", "saleStoreName", "verifyStoreId", "verifyStoreName",
        "saleTime", "verifyTime", "receivedAmountCent", "frozenFeeBaseCent",
        "actualFeeRate", "frozenFeeAmountCent", "refundTime", "adjustmentType",
        "rowType", "invoiceNumber", "submittedAt", "invoiceStatus", "settledAt",
        "rejectionReason",
    }.issubset(row)
    assert row["storeName"] == "Store One Historical"
    assert row["sapCode"] == "SAP-STORE-ONE-HIST"
    assert row["invoiceNumber"] == "12345678901234567890"
    assert row["actualFeeRate"] == "0.100000"
    assert "originalBusinessMonth" not in row
    assert "statementPostingMonth" not in row
    assert "refundAmountCent" not in row
    assert payload["definitions"]["frozenFeeAmountCent"]["source"] == (
        "settlement_statement_entry.fee_amount_cent"
    )
    assert {
        "statementEntryId", "statementId", "storeId", "storeName", "sapCode",
        "statementMonth", "feeDirection", "orderId", "couponId", "orderStatus",
        "couponStatus", "productName", "skuId", "skuName", "saleChannel",
        "saleStoreId", "saleStoreName", "verifyStoreId", "verifyStoreName",
        "saleTime", "verifyTime", "receivedAmountCent", "frozenFeeBaseCent",
        "actualFeeRate", "frozenFeeAmountCent", "refundTime", "adjustmentType",
        "rowType", "invoiceNumber", "submittedAt", "invoiceStatus", "settledAt",
        "rejectionReason", "importedAt", "settlementStatus",
        "factoryDeductionDate", "factoryDeductionAmountCent",
    }.issubset(payload["definitions"])

    adjustment_page = client.get(
        "/api/v1/admin/finance/order-details",
        params={
            "month": "2026-08", "feeDirection": "PROMOTION", "storeId": "store-1",
            "sapCode": "SAP-STORE-ONE-HIST", "invoiceNumber": "12345678901234567890",
            "orderId": "order-promotion-current", "skuId": "sku-promotion-current",
            "saleChannel": "short_video", "invoiceStatus": "APPROVED_SETTLED",
            "submittedFrom": "2026-10-05T00:00:00+00:00",
            "submittedTo": "2026-10-06T00:00:00+00:00",
            "verifyFrom": "2026-08-01T00:00:00+00:00",
            "verifyTo": "2026-08-31T23:59:59+00:00", "page": 2, "pageSize": 1,
        },
    )
    assert adjustment_page.status_code == 200
    adjustment = adjustment_page.json()["data"]["list"][0]
    assert adjustment["rowType"] == "ADJUSTMENT"
    assert adjustment["frozenFeeBaseCent"] == -2000
    assert adjustment["frozenFeeAmountCent"] == -200
    assert adjustment["refundTime"] == "2026-08-25T10:00:00+00:00"

    exported = client.get(
        "/api/v1/admin/finance/order-details/export",
        params={
            "month": "2026-08", "feeDirection": "PROMOTION", "storeId": "store-1",
            "sapCode": "SAP-STORE-ONE-HIST", "invoiceNumber": "12345678901234567890",
            "orderId": "order-promotion-current", "skuId": "sku-promotion-current",
            "saleChannel": "short_video", "invoiceStatus": "APPROVED_SETTLED",
            "submittedFrom": "2026-10-05T00:00:00+00:00",
            "submittedTo": "2026-10-06T00:00:00+00:00",
            "verifyFrom": "2026-08-01T00:00:00+00:00",
            "verifyTo": "2026-08-31T23:59:59+00:00",
        },
    )
    assert exported.status_code == 200
    exported_text = exported.content.decode("utf-8-sig")
    assert "store_name" in exported_text.splitlines()[0]
    assert "order-promotion-current" in exported_text
    audit = db_session.scalar(
        select(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type == "FINANCE_ORDER_DETAILS_EXPORT",
            FinanceOperationAudit.result_status == 1,
        )
    )
    assert audit is not None
    assert audit.after_snapshot == {
        "filters": {
            "feeDirection": "PROMOTION", "invoiceNumber": "12345678901234567890",
            "month": "2026-08", "orderId": "order-promotion-current",
            "saleChannel": "short_video", "sapCode": "SAP-STORE-ONE-HIST",
            "skuId": "sku-promotion-current", "storeId": "store-1",
            "submittedFrom": "2026-10-05T00:00:00+00:00",
            "submittedTo": "2026-10-06T00:00:00+00:00",
            "verifyFrom": "2026-08-01T00:00:00+00:00",
            "verifyTo": "2026-08-31T23:59:59+00:00",
            "invoiceStatus": "APPROVED_SETTLED",
        },
        "rowCount": 2, "result": "SUCCESS",
    }

    management = client.get(
        "/api/v1/admin/finance/order-details",
        params={
            "month": "2026-08", "feeDirection": "MANAGEMENT",
            "invoiceNumber": "12345678901234567891", "invoiceStatus": "SETTLED",
        },
    )
    assert management.status_code == 200
    management_row = management.json()["data"]["list"][0]
    assert management_row["settlementStatus"] == "SETTLED"
    assert management_row["invoiceStatus"] is None
    assert management_row["importedAt"] == "2026-10-05T00:00:00+00:00"


def test_admin_finance_order_details_export_empty_result_writes_failure_audit_and_header(
    client: TestClient, db_session: Session
) -> None:
    """An empty export stays recoverable and retains an auditable header-only file."""
    _login(client)
    exported = client.get(
        "/api/v1/admin/finance/order-details/export",
        params={"month": "2026-08", "feeDirection": "PROMOTION"},
    )

    assert exported.status_code == 200
    assert exported.content.startswith(b"\xef\xbb\xbf")
    assert len(exported.content.decode("utf-8-sig").splitlines()) == 1
    audit = db_session.scalar(
        select(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type == "FINANCE_ORDER_DETAILS_EXPORT",
            FinanceOperationAudit.result_status == 2,
        )
    )
    assert audit is not None
    assert audit.after_snapshot == {
        "filters": {"feeDirection": "PROMOTION", "month": "2026-08"},
        "rowCount": 0, "result": "EMPTY",
    }


def test_admin_finance_order_details_export_limit_writes_failure_audit(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login(client)
    _seed_finance_query_facts(db_session)
    monkeypatch.setattr(dashboard_routes, "MAX_FINANCE_ORDER_EXPORT_ROWS", 0)

    exported = client.get(
        "/api/v1/admin/finance/order-details/export",
        params={"month": "2026-08", "feeDirection": "PROMOTION"},
    )

    assert exported.status_code == 413
    audit = db_session.scalar(
        select(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type == "FINANCE_ORDER_DETAILS_EXPORT",
            FinanceOperationAudit.result_status == 3,
        )
    )
    assert audit is not None
    assert audit.after_snapshot == {
        "filters": {"feeDirection": "PROMOTION", "month": "2026-08"},
        "rowCount": 1,
        "result": "LIMIT_EXCEEDED",
    }


def test_admin_finance_order_details_never_falls_back_to_mutable_raw_or_dimension_facts(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    _seed_finance_query_facts(db_session)
    entry = db_session.scalar(
        select(SettlementStatementEntry).where(
            SettlementStatementEntry.statement_entry_id == "entry-promotion-current"
        )
    )
    order = db_session.scalar(
        select(RawDouyinOrder).where(
            RawDouyinOrder.order_id == "order-promotion-current"
        )
    )
    coupon = db_session.scalar(
        select(RawDouyinOrderCoupon).where(
            RawDouyinOrderCoupon.coupon_id == "coupon-promotion-current"
        )
    )
    product = db_session.scalar(
        select(DimSkuProductRule).where(
            DimSkuProductRule.sku_id == "sku-promotion-current"
        )
    )
    verify = db_session.scalar(
        select(RawDouyinVerifyRecord).where(
            RawDouyinVerifyRecord.verify_id == "verify-promotion-current"
        )
    )
    assert entry is not None and order is not None and coupon is not None
    assert product is not None and verify is not None
    entry.verify_time_snapshot = None  # legal empty snapshot must remain empty
    order.order_status = "MUTATED"
    order.order_status_normalized = "MUTATED"
    order.product_name = "Mutable Product"
    coupon.coupon_status = "MUTATED"
    coupon.coupon_status_normalized = "MUTATED"
    product.product_name = "Mutable Dimension Product"
    product.sku_name = "Mutable Dimension SKU"
    verify.verify_time = datetime(2026, 8, 30, 9, tzinfo=timezone.utc)
    db_session.commit()

    listed = client.get(
        "/api/v1/admin/finance/order-details",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "orderId": "order-promotion-current",
            "page": 1,
            "pageSize": 20,
        },
    )
    assert listed.status_code == 200
    row = listed.json()["data"]["list"][0]
    assert row["orderStatus"] == "PAID"
    assert row["couponStatus"] == "USED"
    assert row["productName"] == "Promotion Product"
    assert row["skuName"] == "Promotion SKU"
    assert row["verifyTime"] is None

    filtered = client.get(
        "/api/v1/admin/finance/order-details",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "orderId": "order-promotion-current",
            "verifyFrom": "2026-08-29T00:00:00+00:00",
            "verifyTo": "2026-08-31T23:59:59+00:00",
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["data"]["total"] == 0


def test_admin_finance_order_details_export_query_failure_persists_failure_audit(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login(client)

    def fail_query(_filters: dict):
        raise RuntimeError("projection construction failed")

    monkeypatch.setattr(dashboard_routes, "_finance_order_details_query", fail_query)
    with pytest.raises(RuntimeError, match="projection construction failed"):
        client.get(
            "/api/v1/admin/finance/order-details/export",
            params={"month": "2026-08", "feeDirection": "PROMOTION"},
        )

    db_session.expire_all()
    audit = db_session.scalar(
        select(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type == "FINANCE_ORDER_DETAILS_EXPORT",
            FinanceOperationAudit.result_status == 3,
        )
    )
    assert audit is not None
    assert audit.after_snapshot["result"] == "QUERY_OR_PROJECTION_FAILED"
    assert audit.after_snapshot["rowCount"] == 0


def test_admin_finance_order_details_export_csv_failure_has_no_success_audit(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login(client)
    _seed_finance_query_facts(db_session)

    def fail_csv(_rows: list[dict]) -> str:
        raise RuntimeError("csv generation failed")

    monkeypatch.setattr(dashboard_routes, "_finance_order_detail_csv", fail_csv)
    with pytest.raises(RuntimeError, match="csv generation failed"):
        client.get(
            "/api/v1/admin/finance/order-details/export",
            params={"month": "2026-08", "feeDirection": "PROMOTION"},
        )

    db_session.expire_all()
    audits = list(
        db_session.scalars(
            select(FinanceOperationAudit).where(
                FinanceOperationAudit.operation_type == "FINANCE_ORDER_DETAILS_EXPORT"
            )
        )
    )
    assert [audit.after_snapshot["result"] for audit in audits] == [
        "CSV_GENERATION_FAILED"
    ]
    assert audits[0].result_status == 3


def test_admin_finance_order_details_export_projection_failure_persists_failure_audit(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _login(client)
    _seed_finance_query_facts(db_session)

    def fail_projection(_row, _direction: str) -> dict:
        raise RuntimeError("row projection failed")

    monkeypatch.setattr(dashboard_routes, "_finance_order_detail_item", fail_projection)
    with pytest.raises(RuntimeError, match="row projection failed"):
        client.get(
            "/api/v1/admin/finance/order-details/export",
            params={"month": "2026-08", "feeDirection": "PROMOTION"},
        )

    db_session.expire_all()
    audit = db_session.scalar(
        select(FinanceOperationAudit).where(
            FinanceOperationAudit.operation_type == "FINANCE_ORDER_DETAILS_EXPORT",
            FinanceOperationAudit.result_status == 3,
        )
    )
    assert audit is not None
    assert audit.after_snapshot["result"] == "QUERY_OR_PROJECTION_FAILED"
    assert audit.after_snapshot["rowCount"] == 2


def test_admin_accepts_dispute_with_adjustment_as_new_statement_version(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    db_session.add(
        SettlementStatementEntry(
            statement_entry_id="entry-dispute-admin-transition",
            statement_id="statement-1-v2",
            statement_line_id="line-dispute-admin-transition",
            source_type=1,
            source_record_id="source-dispute-admin-transition",
            original_fee_result_id="fee-result-dispute-admin-transition",
            coupon_id="coupon-dispute-admin-transition",
            order_id="order-dispute-admin-transition",
            fee_direction=1,
            original_business_month="2026-08",
            statement_posting_month="2026-08",
            base_amount_cent=11000,
            fee_amount_cent=1100,
            rule_version="rule-v1",
            order_status_snapshot="COMPLETED",
            coupon_status_snapshot="USED",
            product_name_snapshot="Frozen Dispute Product",
            sku_id_snapshot="sku-dispute-frozen",
            sku_name_snapshot="Frozen Dispute SKU",
            sale_channel_snapshot="short_video",
            sale_store_id_snapshot="store-sale-frozen",
            sale_store_snapshot="Frozen Sale Store",
            verify_store_id_snapshot="store-verify-frozen",
            verify_store_snapshot="Frozen Verify Store",
            sale_time_snapshot=datetime(2026, 8, 8, tzinfo=timezone.utc),
            verify_time_snapshot=datetime(2026, 8, 9, tzinfo=timezone.utc),
            received_amount_cent_snapshot=11000,
            fee_rate_snapshot=Decimal("0.100000"),
        )
    )
    db_session.commit()
    created = client.post(
        "/api/v1/store-settlements/statement-1-v2/disputes",
        json={
            "feeDirection": "PROMOTION",
            "disputeType": "AMOUNT_ERROR",
            "description": "推广费金额需要更正",
            "contactName": "门店联系人",
            "contactPhone": "13812345678",
            "disputedAmountCent": 100,
            "orders": [
                {
                    "orderId": "order-dispute-admin-transition",
                    "couponId": "coupon-dispute-admin-transition",
                    "disputedAmountCent": 100,
                }
            ],
            "evidence": [{"objectKey": "evidence/dispute-admin-transition.pdf"}],
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "dispute-admin-transition-create-0001"},
    )
    assert created.status_code == 200
    dispute_id = created.json()["data"]["disputeId"]

    listed = client.get(
        "/api/v1/admin/disputes",
        params={"month": "2026-08", "feeDirection": "PROMOTION"},
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["list"][0]["disputeId"] == dispute_id

    transitioned = client.post(
        f"/api/v1/admin/disputes/{dispute_id}/transitions",
        json={
            "targetStatus": "ACCEPTED_WITH_ADJUSTMENT",
            "resolutionNote": "确认扣减 100 分",
            "adjustmentAmountCent": -100,
            "readVersion": 2,
        },
        headers={"Idempotency-Key": "dispute-admin-transition-0001"},
    )
    assert transitioned.status_code == 200
    data = transitioned.json()["data"]
    assert data["status"] == "ACCEPTED_WITH_ADJUSTMENT"
    assert data["previousStatementId"] == "statement-1-v2"
    assert data["currentVersion"] == 3

    db_session.expire_all()
    current_statement = db_session.scalar(
        select(SettlementStatement).where(
            SettlementStatement.store_id == "store-1",
            SettlementStatement.statement_month == "2026-08",
            SettlementStatement.is_current.is_(True),
        )
    )
    assert current_statement is not None
    assert current_statement.version_no == 3
    assert current_statement.promotion_net_fee_cent == 1000
    assert current_statement.store_name_snapshot == "Store One Historical"
    assert current_statement.sap_code_snapshot == "SAP-STORE-ONE-HIST"
    assert current_statement.store_snapshot_status == "LIVE_CAPTURED"
    assert current_statement.store_snapshot_profile_id == "profile-store-one-hist"
    current_entries = list(db_session.scalars(
        select(SettlementStatementEntry)
        .where(SettlementStatementEntry.statement_id == current_statement.statement_id)
        .order_by(SettlementStatementEntry.source_type)
    ))
    assert len(current_entries) == 2
    for entry in current_entries:
        assert entry.order_status_snapshot == "COMPLETED"
        assert entry.coupon_status_snapshot == "USED"
        assert entry.product_name_snapshot == "Frozen Dispute Product"
        assert entry.sku_id_snapshot == "sku-dispute-frozen"
        assert entry.sku_name_snapshot == "Frozen Dispute SKU"
        assert entry.sale_channel_snapshot == "short_video"
        assert entry.sale_store_id_snapshot == "store-sale-frozen"
        assert entry.sale_store_snapshot == "Frozen Sale Store"
        assert entry.verify_store_id_snapshot == "store-verify-frozen"
        assert entry.verify_store_snapshot == "Frozen Verify Store"
        assert entry.received_amount_cent_snapshot == 11000
        assert entry.fee_rate_snapshot == Decimal("0.100000")
    assert current_entries[1].adjustment_type_snapshot == 3
    assert current_entries[1].refund_at_snapshot is not None
    assert db_session.scalar(select(FinanceOperationAudit).where(
        FinanceOperationAudit.target_id == dispute_id
    )) is not None
