from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.auth import AuthContext, get_current_user  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    DimStore,
    FinanceImportBatch,
    FinanceImportRow,
    FinanceOperationAudit,
    InvoiceRecord,
    InvoiceStatusEvent,
    JobRun,
    PromotionInvoice,
    PromotionInvoiceAllocation,
    SapSuggestion,
    SettlementDispute,
    SettlementDisputeOrder,
    SettlementStatement,
    SettlementStatementConfirmation,
    SettlementStatementEntry,
    StoreFinanceProfile,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
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


def _act_as_store(client: TestClient, store_id: str = "g5-store") -> None:
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id=f"{store_id}-user",
        username=f"{store_id}-user",
        display_name="G5 Store User",
        role="store",
        store_ids=(store_id,),
        auth_type="user",
        store_scope_mode="assigned",
    )


def _act_as_restricted_finance_admin(
    client: TestClient,
    *,
    store_ids: tuple[str, ...],
    page_keys: tuple[str, ...] = (
        "FIN01",
        "FIN02",
        "FIN03",
        "FIN04",
        "FIN05",
        "FIN06",
    ),
) -> None:
    client.app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="g5-restricted-admin",
        username="g5-restricted-admin",
        display_name="G5 Restricted Admin",
        role="admin",
        store_ids=store_ids,
        auth_type="user",
        store_scope_mode="specified",
        page_keys=page_keys,
    )


def _seed_store_and_statement(
    db_session: Session,
    *,
    store_id: str = "g5-store",
    statement_id: str = "g5-statement",
    statement_month: str = "2026-08",
    promotion_amount_cent: int = 1000,
    sap_code_snapshot: str = "SAP-HISTORICAL",
) -> SettlementStatement:
    store = DimStore(store_id=store_id, store_name="G5 Store", is_active=True)
    statement = SettlementStatement(
        statement_id=statement_id,
        store_id=store_id,
        statement_month=statement_month,
        version_no=1,
        is_current=True,
        statement_status=4,
        promotion_original_fee_cent=promotion_amount_cent,
        promotion_adjustment_fee_cent=0,
        promotion_net_fee_cent=promotion_amount_cent,
        management_original_fee_cent=0,
        management_adjustment_fee_cent=0,
        management_net_fee_cent=0,
        store_name_snapshot="G5 Store Historical",
        sap_code_snapshot=sap_code_snapshot,
        store_snapshot_status="LIVE_CAPTURED",
        store_snapshot_profile_id="g5-historical-profile",
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    db_session.add_all([store, statement])
    db_session.commit()
    return statement


def _seed_promotion_invoice(
    db_session: Session,
    *,
    statement: SettlementStatement,
    invoice_id: str = "g5-invoice",
    invoice_status: int = 3,
    invoice_amount_cent: int = 1000,
    invoice_number: str = "62345678901234567890",
) -> PromotionInvoice:
    invoice = PromotionInvoice(
        invoice_id=invoice_id,
        physical_invoice_id=f"physical-{invoice_id}",
        store_id=statement.store_id,
        version_no=1,
        version_kind=1,
        is_current=True,
        invoice_number=invoice_number,
        invoice_date=date(2026, 8, 10),
        invoice_amount_cent=invoice_amount_cent,
        buyer_name="比亚迪汽车销售有限公司",
        tax_rate_percent=6,
        invoice_status=invoice_status,
        registered_by="g5-store-user",
        registered_at=datetime(2026, 8, 12, 8, tzinfo=timezone.utc),
    )
    allocation = PromotionInvoiceAllocation(
        allocation_id=f"allocation-{invoice_id}",
        invoice_id=invoice_id,
        store_id=statement.store_id,
        statement_id=statement.statement_id,
        statement_month=statement.statement_month,
        settlement_batch_month="2026-08",
        allocated_amount_cent=invoice_amount_cent,
        is_current=True,
    )
    db_session.add_all([invoice, allocation])
    db_session.commit()
    return invoice


def _seed_management_order_case(
    db_session: Session,
    *,
    case: str,
    confirmed_amount_cent: int = 1000,
    factory_deduction_amount_cent: int | None,
) -> SettlementStatement:
    statement = _seed_store_and_statement(
        db_session,
        store_id=f"g5-management-order-{case}-store",
        statement_id=f"g5-management-order-{case}-statement",
        promotion_amount_cent=0,
        sap_code_snapshot=f"SAP-MGMT-ORDER-{case.upper()}",
    )
    statement.management_original_fee_cent = confirmed_amount_cent
    statement.management_net_fee_cent = confirmed_amount_cent
    db_session.add_all(
        [
            SettlementStatementConfirmation(
                confirmation_id=f"g5-management-order-{case}-confirmation",
                statement_id=statement.statement_id,
                fee_direction=2,
                confirmation_status=1,
                confirmed_amount_cent=confirmed_amount_cent,
                confirmed_by="g5-management-order-store-user",
                confirmed_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
            ),
            SettlementStatementEntry(
                statement_entry_id=f"g5-management-order-{case}-entry",
                statement_id=statement.statement_id,
                statement_line_id=f"g5-management-order-{case}-line",
                source_type=1,
                source_record_id=f"g5-management-order-{case}-source",
                original_fee_result_id=f"g5-management-order-{case}-fee",
                coupon_id=f"g5-management-order-{case}-coupon",
                order_id=f"g5-management-order-{case}",
                fee_direction=2,
                original_business_month="2026-08",
                statement_posting_month="2026-08",
                product_scope="LOCAL_LIFE",
                product_type="SERVICE_PRODUCT",
                base_amount_cent=10000,
                fee_amount_cent=confirmed_amount_cent,
                rule_version="g5-management-order-v1",
                order_status_snapshot="COMPLETED",
                product_name_snapshot=f"Management {case}",
                sku_id_snapshot=f"g5-management-{case}-sku",
                sku_name_snapshot=f"Management {case} SKU",
                sale_channel_snapshot="short_video",
                verify_time_snapshot=datetime(2026, 8, 3, tzinfo=timezone.utc),
            ),
        ]
    )
    if factory_deduction_amount_cent is not None:
        suffix = {"partial": "81", "full": "82"}[case]
        db_session.add(
            InvoiceRecord(
                invoice_id=f"g5-management-order-{case}-invoice",
                store_id=statement.store_id,
                statement_month=statement.statement_month,
                statement_id=statement.statement_id,
                fee_direction=2,
                version_no=1,
                is_current=True,
                invoice_number=f"123456789012345678{suffix}",
                invoice_date=date(2026, 8, 10),
                invoice_amount_cent=confirmed_amount_cent,
                invoice_status=3,
                source_type=2,
                factory_deduction_date=date(2026, 8, 21),
                factory_deduction_amount_cent=factory_deduction_amount_cent,
                registered_by="finance-admin",
                registered_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
            )
        )
    db_session.commit()
    return statement


def test_promotion_summary_has_exactly_five_cards_and_rejected_amount_is_pending(
    client: TestClient,
    db_session: Session,
) -> None:
    statement = _seed_store_and_statement(db_session)
    db_session.add(
        SettlementStatementConfirmation(
            confirmation_id="g5-summary-confirmation",
            statement_id=statement.statement_id,
            fee_direction=1,
            confirmation_status=1,
            confirmed_amount_cent=1000,
            confirmed_by="g5-store-user",
            confirmed_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    _seed_promotion_invoice(
        db_session,
        statement=statement,
        invoice_id="g5-rejected-invoice",
        invoice_status=4,
    )
    _login(client)

    response = client.get(
        "/api/v1/admin/finance/summary",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
            "storeId": "g5-store",
        },
    )

    assert response.status_code == 200
    metrics = response.json()["data"]["metrics"]
    assert set(metrics) == {
        "statementTotalCent",
        "confirmedAmountCent",
        "pendingInvoiceAmountCent",
        "issuedAmountCent",
        "settledOrDeductedAmountCent",
    }
    assert metrics == {
        "statementTotalCent": 1000,
        "confirmedAmountCent": 1000,
        "pendingInvoiceAmountCent": 1000,
        "issuedAmountCent": 0,
        "settledOrDeductedAmountCent": 0,
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/finance/summary",
        "/api/v1/admin/finance/invoices",
        "/api/v1/admin/finance/invoices/export",
    ],
)
def test_promotion_invoice_detail_contract_rejects_pending_invoice_filter(
    path: str,
    client: TestClient,
) -> None:
    _login(client)
    response = client.get(
        path,
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
            "invoiceStatus": "PENDING_INVOICE",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["field"] == "invoiceStatus"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/finance/summary",
        "/api/v1/admin/finance/invoices",
        "/api/v1/admin/finance/invoices/export",
    ],
)
def test_management_invoice_contract_rejects_promotion_review_status(
    path: str,
    client: TestClient,
) -> None:
    _login(client)
    response = client.get(
        path,
        params={
            "month": "2026-08",
            "feeDirection": "MANAGEMENT",
            "metricScope": "MONTH",
            "invoiceStatus": "SUBMITTED_PENDING_FACTORY_REVIEW",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["field"] == "invoiceStatus"


def test_order_list_and_export_share_q_status_dates_and_frozen_product_type(
    client: TestClient,
    db_session: Session,
) -> None:
    statement = _seed_store_and_statement(db_session)
    db_session.add_all(
        [
            SettlementStatementEntry(
                statement_entry_id="g5-entry-needle",
                statement_id=statement.statement_id,
                statement_line_id="g5-line",
                source_type=1,
                source_record_id="g5-source-needle",
                original_fee_result_id="g5-fee-needle",
                coupon_id="g5-coupon-needle",
                order_id="needle-order-001",
                fee_direction=1,
                original_business_month="2026-08",
                statement_posting_month="2026-08",
                product_scope="LOCAL_LIFE",
                product_type="SERVICE_PRODUCT",
                base_amount_cent=10000,
                fee_amount_cent=1000,
                rule_version="g5-rule-v1",
                order_status_snapshot="COMPLETED",
                product_name_snapshot="Needle Product",
                sku_id_snapshot="g5-sku-needle",
                sku_name_snapshot="Needle SKU",
                sale_channel_snapshot="short_video",
                sale_time_snapshot=datetime(2026, 8, 2, tzinfo=timezone.utc),
                verify_time_snapshot=datetime(2026, 8, 3, tzinfo=timezone.utc),
                received_amount_cent_snapshot=10000,
                fee_rate_snapshot=0.1,
            ),
            SettlementStatementEntry(
                statement_entry_id="g5-entry-other",
                statement_id=statement.statement_id,
                statement_line_id="g5-line",
                source_type=1,
                source_record_id="g5-source-other",
                original_fee_result_id="g5-fee-other",
                coupon_id="g5-coupon-other",
                order_id="other-order-002",
                fee_direction=1,
                original_business_month="2026-08",
                statement_posting_month="2026-08",
                product_scope="LOCAL_LIFE",
                product_type="OTHER_PRODUCT",
                base_amount_cent=20000,
                fee_amount_cent=2000,
                rule_version="g5-rule-v1",
                order_status_snapshot="COMPLETED",
                product_name_snapshot="Other Product",
                sku_id_snapshot="g5-sku-other",
                sku_name_snapshot="Other SKU",
                sale_channel_snapshot="short_video",
                sale_time_snapshot=datetime(2026, 8, 2, tzinfo=timezone.utc),
                verify_time_snapshot=datetime(2026, 8, 3, tzinfo=timezone.utc),
                received_amount_cent_snapshot=20000,
                fee_rate_snapshot=0.1,
            ),
        ]
    )
    db_session.commit()
    invoice = _seed_promotion_invoice(db_session, statement=statement)
    db_session.add(
        InvoiceStatusEvent(
            event_id="g5-settled-event",
            invoice_id=invoice.invoice_id,
            event_type=3,
            from_status=2,
            to_status=3,
            operator_id="finance-admin",
            business_date=date(2026, 8, 15),
            occurred_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    _login(client)
    filters = {
        "month": "2026-08",
        "feeDirection": "PROMOTION",
        "q": "needle-order",
        "invoiceStatus": "APPROVED_SETTLED",
        "settlementStatus": "SETTLED",
        "submittedFrom": "2026-08-12T00:00:00+00:00",
        "submittedTo": "2026-08-12T23:59:59+00:00",
        "verifyFrom": "2026-08-01T00:00:00+00:00",
        "verifyTo": "2026-08-31T23:59:59+00:00",
    }

    listed = client.get("/api/v1/admin/finance/order-details", params=filters)
    exported = client.get(
        "/api/v1/admin/finance/order-details/export", params=filters
    )

    assert listed.status_code == 200
    payload = listed.json()["data"]
    assert payload["total"] == 1
    row = payload["list"][0]
    assert row["orderId"] == "needle-order-001"
    assert row["billingStoreId"] == "g5-store"
    assert row["billingStoreName"] == "G5 Store Historical"
    assert row["serviceStoreName"] == "G5 Store Historical"
    assert row["effectiveSapCode"] == "SAP-HISTORICAL"
    assert row["productType"] == "SERVICE_PRODUCT"
    assert row["settlementStatus"] == "SETTLED"
    assert row["settlementDate"] == "2026-08-15"
    assert payload["definitions"]["productType"]["source"] == (
        "settlement_statement_entry.product_type"
    )
    assert payload["definitions"]["billingStoreId"]["source"] == (
        "settlement_statement.store_id"
    )
    assert payload["definitions"]["serviceStoreName"]["source"] == (
        "settlement_statement.store_name_snapshot"
    )
    assert payload["definitions"]["effectiveSapCode"]["source"] == (
        "settlement_statement.sap_code_snapshot"
    )
    assert exported.status_code == 200
    exported_text = exported.content.decode("utf-8-sig")
    exported_header = exported_text.splitlines()[0]
    assert "product_type" in exported_header
    assert "billing_store_id" in exported_header
    assert "billing_store_name" in exported_header
    assert "service_store_name" in exported_header
    assert "effective_sap_code" in exported_header
    assert "settlement_date" in exported_header
    assert "needle-order-001" in exported_text
    assert "other-order-002" not in exported_text
    assert '"q":"needle-order"' in exported.headers["x-export-filters"]
    assert '"settlementStatus":"SETTLED"' in exported.headers[
        "x-export-filters"
    ]


def test_management_order_without_invoice_accepts_pending_filter_and_is_unsettled(
    client: TestClient,
    db_session: Session,
) -> None:
    statement = _seed_management_order_case(
        db_session,
        case="pending",
        factory_deduction_amount_cent=None,
    )
    _login(client)

    response = client.get(
        "/api/v1/admin/finance/order-details",
        params={
            "month": "2026-08",
            "feeDirection": "MANAGEMENT",
            "invoiceStatus": "PENDING_INVOICE",
            "settlementStatus": "UNSETTLED",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
    row = response.json()["data"]["list"][0]
    assert row["statementId"] == statement.statement_id
    assert row["invoiceStatus"] == "PENDING_INVOICE"
    assert row["settlementStatus"] == "UNSETTLED"
    assert row["factoryDeductionAmountCent"] is None


def test_management_order_partial_factory_deduction_remains_unsettled(
    client: TestClient,
    db_session: Session,
) -> None:
    statement = _seed_management_order_case(
        db_session,
        case="partial",
        factory_deduction_amount_cent=400,
    )
    _login(client)
    filters = {
        "month": "2026-08",
        "feeDirection": "MANAGEMENT",
        "invoiceStatus": "APPROVED_SETTLED",
        "settlementStatus": "UNSETTLED",
    }

    response = client.get(
        "/api/v1/admin/finance/order-details", params=filters
    )
    settled = client.get(
        "/api/v1/admin/finance/order-details",
        params={**filters, "settlementStatus": "SETTLED"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
    row = response.json()["data"]["list"][0]
    assert row["statementId"] == statement.statement_id
    assert row["invoiceStatus"] == "APPROVED_SETTLED"
    assert row["settlementStatus"] == "UNSETTLED"
    assert row["factoryDeductionAmountCent"] == 400
    assert settled.status_code == 200
    assert settled.json()["data"]["total"] == 0


def test_management_order_full_factory_deduction_is_settled_in_list_and_export(
    client: TestClient,
    db_session: Session,
) -> None:
    statement = _seed_management_order_case(
        db_session,
        case="full",
        factory_deduction_amount_cent=1000,
    )
    _login(client)
    filters = {
        "month": "2026-08",
        "feeDirection": "MANAGEMENT",
        "invoiceStatus": "APPROVED_SETTLED",
        "settlementStatus": "SETTLED",
    }

    listed = client.get(
        "/api/v1/admin/finance/order-details", params=filters
    )
    exported = client.get(
        "/api/v1/admin/finance/order-details/export", params=filters
    )

    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    row = listed.json()["data"]["list"][0]
    assert row["statementId"] == statement.statement_id
    assert row["invoiceStatus"] == "APPROVED_SETTLED"
    assert row["settlementStatus"] == "SETTLED"
    assert row["factoryDeductionAmountCent"] == 1000
    assert exported.status_code == 200
    exported_text = exported.content.decode("utf-8-sig")
    assert "g5-management-order-full" in exported_text
    assert "APPROVED_SETTLED" in exported_text
    assert "SETTLED" in exported_text


def test_invoice_list_exposes_only_official_frozen_contract_facts(
    client: TestClient,
    db_session: Session,
) -> None:
    statement = _seed_store_and_statement(
        db_session, promotion_amount_cent=1100
    )
    db_session.add_all(
        [
            SettlementStatementConfirmation(
                confirmation_id="g5-invoice-confirmation",
                statement_id=statement.statement_id,
                fee_direction=1,
                confirmation_status=1,
                confirmed_amount_cent=1100,
                confirmed_by="g5-store-user",
            ),
            StoreFinanceProfile(
                profile_id="g5-finance-profile-v1",
                store_id="g5-store",
                profile_type=1,
                source_type=1,
                version_no=1,
                is_current=True,
                store_name_snapshot="G5 Store",
                sap_code="SAP-FINANCE-001",
                import_batch_id="g5-basic-import",
                created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
                updated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()
    invoice = _seed_promotion_invoice(
        db_session,
        statement=statement,
        invoice_id="g5-contract-invoice",
        invoice_status=4,
        invoice_amount_cent=1100,
    )
    db_session.add(
        InvoiceStatusEvent(
            event_id="g5-rejection-event",
            invoice_id=invoice.invoice_id,
            event_type=4,
            from_status=2,
            to_status=4,
            operator_id="finance-admin",
            result_reason="发票购方信息不一致",
            occurred_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    _login(client)

    response = client.get(
        "/api/v1/admin/finance/invoices",
        params={"month": "2026-08", "feeDirection": "PROMOTION"},
    )

    assert response.status_code == 200
    row = response.json()["data"]["list"][0]
    assert row["storeName"] == "G5 Store Historical"
    assert row["effectiveSapCode"] == "SAP-FINANCE-001"
    assert row["statementAmountCent"] == 1100
    assert row["confirmedAmountCent"] == 1100
    assert row["rejectionReason"] == "发票购方信息不一致"
    assert row["settlementBatchMonth"] == "2026-08"


def test_fee_summary_list_and_export_apply_one_shared_filter_contract(
    client: TestClient,
    db_session: Session,
) -> None:
    needle = _seed_store_and_statement(
        db_session,
        store_id="g5-needle-store",
        statement_id="g5-needle-statement",
        promotion_amount_cent=1000,
        sap_code_snapshot="SAP-NEEDLE",
    )
    other = _seed_store_and_statement(
        db_session,
        store_id="g5-other-store",
        statement_id="g5-other-statement",
        promotion_amount_cent=2000,
        sap_code_snapshot="SAP-OTHER",
    )
    db_session.add_all(
        [
            SettlementStatementConfirmation(
                confirmation_id="g5-needle-filter-confirmation",
                statement_id=needle.statement_id,
                fee_direction=1,
                confirmation_status=1,
                confirmed_amount_cent=1000,
                confirmed_by="g5-needle-store-user",
            ),
            SettlementStatementConfirmation(
                confirmation_id="g5-other-filter-confirmation",
                statement_id=other.statement_id,
                fee_direction=1,
                confirmation_status=1,
                confirmed_amount_cent=2000,
                confirmed_by="g5-other-store-user",
            ),
        ]
    )
    db_session.commit()
    _seed_promotion_invoice(
        db_session,
        statement=needle,
        invoice_id="g5-needle-filter-invoice",
        invoice_status=4,
        invoice_amount_cent=1000,
        invoice_number="71345678901234567890",
    )
    _seed_promotion_invoice(
        db_session,
        statement=other,
        invoice_id="g5-other-filter-invoice",
        invoice_status=4,
        invoice_amount_cent=2000,
        invoice_number="72345678901234567890",
    )
    _login(client)
    filters = {
        "month": "2026-08",
        "feeDirection": "PROMOTION",
        "metricScope": "MONTH",
        "q": "SAP-NEEDLE",
        "invoiceStatus": "REJECTED_REUPLOAD",
    }

    summary = client.get("/api/v1/admin/finance/summary", params=filters)
    listed = client.get("/api/v1/admin/finance/invoices", params=filters)
    exported = client.get(
        "/api/v1/admin/finance/invoices/export", params=filters
    )

    assert summary.status_code == 200
    assert summary.json()["data"]["metrics"] == {
        "statementTotalCent": 1000,
        "confirmedAmountCent": 1000,
        "pendingInvoiceAmountCent": 1000,
        "issuedAmountCent": 0,
        "settledOrDeductedAmountCent": 0,
    }
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    assert listed.json()["data"]["list"][0]["invoiceId"] == (
        "g5-needle-filter-invoice"
    )
    assert exported.status_code == 200
    exported_text = exported.content.decode("utf-8-sig")
    assert "g5-needle-filter-invoice" in exported_text
    assert "g5-other-filter-invoice" not in exported_text


def test_management_confirmed_statement_without_invoice_is_pending_in_list_export_and_summary(
    client: TestClient,
    db_session: Session,
) -> None:
    confirmed = _seed_store_and_statement(
        db_session,
        store_id="g5-management-confirmed-store",
        statement_id="g5-management-confirmed-statement",
        promotion_amount_cent=0,
        sap_code_snapshot="SAP-MGMT-CONFIRMED",
    )
    confirmed.management_original_fee_cent = 2300
    confirmed.management_net_fee_cent = 2300
    unconfirmed = _seed_store_and_statement(
        db_session,
        store_id="g5-management-unconfirmed-store",
        statement_id="g5-management-unconfirmed-statement",
        promotion_amount_cent=0,
        sap_code_snapshot="SAP-MGMT-UNCONFIRMED",
    )
    unconfirmed.management_original_fee_cent = 700
    unconfirmed.management_net_fee_cent = 700
    db_session.add(
        SettlementStatementConfirmation(
            confirmation_id="g5-management-confirmed-fact",
            statement_id=confirmed.statement_id,
            fee_direction=2,
            confirmation_status=1,
            confirmed_amount_cent=2300,
            confirmed_by="g5-management-store-user",
            confirmed_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    _login(client)
    filters = {
        "month": "2026-08",
        "feeDirection": "MANAGEMENT",
        "metricScope": "MONTH",
        "q": "SAP-MGMT",
        "invoiceStatus": "PENDING_INVOICE",
    }

    summary = client.get("/api/v1/admin/finance/summary", params=filters)
    listed = client.get("/api/v1/admin/finance/invoices", params=filters)
    exported = client.get(
        "/api/v1/admin/finance/invoices/export", params=filters
    )

    assert summary.status_code == 200
    assert summary.json()["data"]["metrics"] == {
        "statementTotalCent": 2300,
        "confirmedAmountCent": 2300,
        "pendingInvoiceAmountCent": 2300,
        "issuedAmountCent": 0,
        "settledOrDeductedAmountCent": 0,
    }
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    row = listed.json()["data"]["list"][0]
    assert row["statementId"] == confirmed.statement_id
    assert row["storeId"] == confirmed.store_id
    assert row["status"] == "PENDING_INVOICE"
    assert row["statementAmountCent"] == 2300
    assert row["confirmedAmountCent"] == 2300
    assert row["invoiceId"] is None
    assert row["invoiceNumber"] is None
    assert row["invoiceDate"] is None
    assert row["invoiceAmountCent"] is None
    assert row["registeredAt"] is None
    assert exported.status_code == 200
    exported_text = exported.content.decode("utf-8-sig")
    assert confirmed.statement_id in exported_text
    assert unconfirmed.statement_id not in exported_text
    assert "PENDING_INVOICE" in exported_text


def test_fee_list_and_export_apply_cumulative_metric_scope_like_summary(
    client: TestClient,
    db_session: Session,
) -> None:
    august = _seed_store_and_statement(
        db_session,
        store_id="g5-cumulative-store",
        statement_id="g5-cumulative-aug",
        statement_month="2026-08",
        promotion_amount_cent=1000,
        sap_code_snapshot="SAP-CUMULATIVE",
    )
    september = SettlementStatement(
        statement_id="g5-cumulative-sep",
        store_id="g5-cumulative-store",
        statement_month="2026-09",
        version_no=1,
        is_current=True,
        statement_status=4,
        promotion_original_fee_cent=500,
        promotion_adjustment_fee_cent=0,
        promotion_net_fee_cent=500,
        management_original_fee_cent=0,
        management_adjustment_fee_cent=0,
        management_net_fee_cent=0,
        store_name_snapshot="G5 Cumulative Store",
        sap_code_snapshot="SAP-CUMULATIVE",
        store_snapshot_status="LIVE_CAPTURED",
        store_snapshot_profile_id="g5-cumulative-profile",
    )
    db_session.add_all(
        [
            september,
            SettlementStatementConfirmation(
                confirmation_id="g5-cumulative-aug-confirmation",
                statement_id=august.statement_id,
                fee_direction=1,
                confirmation_status=1,
                confirmed_amount_cent=1000,
                confirmed_by="g5-cumulative-store-user",
            ),
            SettlementStatementConfirmation(
                confirmation_id="g5-cumulative-sep-confirmation",
                statement_id=september.statement_id,
                fee_direction=1,
                confirmation_status=1,
                confirmed_amount_cent=500,
                confirmed_by="g5-cumulative-store-user",
            ),
        ]
    )
    db_session.commit()
    _seed_promotion_invoice(
        db_session,
        statement=august,
        invoice_id="g5-cumulative-aug-invoice",
        invoice_status=4,
        invoice_amount_cent=1000,
        invoice_number="73345678901234567890",
    )
    _seed_promotion_invoice(
        db_session,
        statement=september,
        invoice_id="g5-cumulative-sep-invoice",
        invoice_status=4,
        invoice_amount_cent=500,
        invoice_number="74345678901234567890",
    )
    _login(client)
    filters = {
        "month": "2026-09",
        "feeDirection": "PROMOTION",
        "metricScope": "CUMULATIVE",
        "q": "SAP-CUMULATIVE",
        "invoiceStatus": "REJECTED_REUPLOAD",
    }

    summary = client.get("/api/v1/admin/finance/summary", params=filters)
    listed = client.get("/api/v1/admin/finance/invoices", params=filters)
    exported = client.get(
        "/api/v1/admin/finance/invoices/export", params=filters
    )

    assert summary.status_code == 200
    assert summary.json()["data"]["metrics"] == {
        "statementTotalCent": 1500,
        "confirmedAmountCent": 500,
        "pendingInvoiceAmountCent": 1500,
        "issuedAmountCent": 0,
        "settledOrDeductedAmountCent": 0,
    }
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 2
    assert exported.status_code == 200
    exported_text = exported.content.decode("utf-8-sig")
    assert "g5-cumulative-aug-invoice" in exported_text
    assert "g5-cumulative-sep-invoice" in exported_text


def test_finance_sap_is_effective_and_single_correction_versions_audits_and_replays(
    client: TestClient,
    db_session: Session,
) -> None:
    statement = _seed_store_and_statement(db_session)
    db_session.add_all(
        [
            FinanceImportBatch(
                batch_id="g5-basic-import",
                import_type=1,
                statement_month="2026-08",
                file_name="basic-info.csv",
                file_sha256="a" * 64,
                normalized_sha256="b" * 64,
                read_version=0,
                current_version=1,
                batch_status=5,
                total_rows=1,
                success_rows=1,
                error_rows=0,
                content_changed=True,
                submitted_by="finance-importer",
                committed_by="finance-importer",
                committed_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            ),
            StoreFinanceProfile(
                profile_id="g5-finance-profile-v1",
                store_id="g5-store",
                profile_type=1,
                source_type=1,
                version_no=1,
                is_current=True,
                store_name_snapshot="G5 Store",
                sap_code="SAP-FINANCE-001",
                import_batch_id="g5-basic-import",
                created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
                updated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            ),
            StoreFinanceProfile(
                profile_id="g5-legacy-suggestion-profile-v7",
                store_id="g5-store",
                profile_type=2,
                source_type=3,
                version_no=7,
                is_current=True,
                store_name_snapshot="G5 Store",
                sap_code="SAP-LEGACY-SUGGESTION-888",
                created_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
                updated_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
            ),
            SapSuggestion(
                suggestion_id="g5-store-sap-v1",
                store_id="g5-store",
                version_no=1,
                is_current=True,
                suggested_sap_code="SAP-STORE-999",
                suggestion_note="门店维护值",
                suggestion_status=1,
                submitted_by="g5-store-user",
                submitted_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()
    _login(client)

    before = client.get(
        "/api/v1/admin/finance/stores",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )
    assert before.status_code == 200
    before_row = before.json()["data"]["list"][0]
    assert before_row["storeMaintainedSapCode"] == "SAP-STORE-999"
    assert before_row["financeImportedSapCode"] == "SAP-FINANCE-001"
    assert before_row["effectiveSapCode"] == "SAP-FINANCE-001"
    assert before_row["effectiveSapVersion"] == 1
    assert before_row["effectiveSapUpdatedBy"] == "finance-importer"
    assert before_row["effectiveSapUpdatedAt"] == "2026-08-04T00:00:00+00:00"
    assert before_row["discrepancyId"] == "g5-store-sap-v1"
    assert before_row["sapStatus"] == "FINANCE_ACTION_REQUIRED"
    assert before_row["discrepancyDetectedAt"] == "2026-08-03T00:00:00+00:00"
    assert "storeSapCode" not in before_row
    assert "financeSapCode" not in before_row
    assert "effectiveVersion" not in before_row
    assert "effectiveOperator" not in before_row
    assert "effectiveAt" not in before_row

    payload = {
        "finalSapCode": "SAP-CORRECTED-002",
        "changeReason": "财务核对后单条矫正",
        "readVersion": 1,
    }
    corrected = client.post(
        "/api/v1/admin/finance/stores/g5-store/sap-corrections",
        json=payload,
        headers={"Idempotency-Key": "g5-sap-correction-0001"},
    )
    replayed = client.post(
        "/api/v1/admin/finance/stores/g5-store/sap-corrections",
        json=payload,
        headers={"Idempotency-Key": "g5-sap-correction-0001"},
    )

    assert corrected.status_code == 200
    assert replayed.status_code == 200
    assert replayed.json()["data"] == corrected.json()["data"]
    correction = corrected.json()["data"]
    assert correction["storeMaintainedSapCode"] == "SAP-STORE-999"
    assert correction["financeImportedSapCode"] == "SAP-CORRECTED-002"
    assert correction["effectiveSapCode"] == "SAP-CORRECTED-002"
    assert correction["effectiveSapVersion"] == 2
    assert correction["effectiveSapUpdatedBy"] == "system-admin"
    assert correction["sapStatus"] == "CONFIRMED"
    assert correction["changeReason"] == "财务核对后单条矫正"

    reused = client.post(
        "/api/v1/admin/finance/stores/g5-store/sap-corrections",
        json={**payload, "finalSapCode": "SAP-DIFFERENT-003"},
        headers={"Idempotency-Key": "g5-sap-correction-0001"},
    )
    stale = client.post(
        "/api/v1/admin/finance/stores/g5-store/sap-corrections",
        json=payload,
        headers={"Idempotency-Key": "g5-sap-correction-stale"},
    )
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert stale.status_code == 409
    assert stale.json()["detail"]["data"]["currentVersion"] == 2

    profiles = list(
        db_session.scalars(
            select(StoreFinanceProfile)
            .where(
                StoreFinanceProfile.store_id == "g5-store",
                StoreFinanceProfile.profile_type == 1,
            )
            .order_by(StoreFinanceProfile.version_no)
        )
    )
    assert [profile.version_no for profile in profiles] == [1, 2]
    assert [profile.is_current for profile in profiles] == [False, True]
    assert profiles[-1].source_type == 3
    assert profiles[-1].import_batch_id is None
    legacy_profiles = list(
        db_session.scalars(
            select(StoreFinanceProfile).where(
                StoreFinanceProfile.store_id == "g5-store",
                StoreFinanceProfile.profile_type == 2,
            )
        )
    )
    assert len(legacy_profiles) == 1
    assert legacy_profiles[0].version_no == 7
    assert legacy_profiles[0].is_current is True
    assert db_session.scalar(
        select(func.count())
        .select_from(FinanceOperationAudit)
        .where(
            FinanceOperationAudit.operation_type == "SAP_SINGLE_CORRECTION",
            FinanceOperationAudit.result_status == 1,
        )
    ) == 1
    db_session.refresh(statement)
    assert statement.sap_code_snapshot == "SAP-HISTORICAL"

    current_suggestion = db_session.scalar(
        select(SapSuggestion).where(
            SapSuggestion.store_id == "g5-store",
            SapSuggestion.is_current.is_(True),
        )
    )
    assert current_suggestion is not None
    current_suggestion.is_current = False
    correction_time = profiles[-1].updated_at
    if correction_time.tzinfo is None:
        correction_time = correction_time.replace(tzinfo=timezone.utc)
    db_session.add(
        SapSuggestion(
            suggestion_id="g5-store-sap-v2",
            store_id="g5-store",
            version_no=2,
            is_current=True,
            suggested_sap_code="SAP-STORE-NEW-003",
            suggestion_note="财务矫正后的门店新建议",
            suggestion_status=1,
            submitted_by="g5-store-user",
            submitted_at=correction_time + timedelta(seconds=1),
        )
    )
    db_session.commit()
    reopened = client.get(
        "/api/v1/admin/finance/stores",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )
    assert reopened.status_code == 200
    reopened_row = reopened.json()["data"]["list"][0]
    assert reopened_row["sapStatus"] == "FINANCE_ACTION_REQUIRED"
    assert reopened_row["discrepancyId"] == "g5-store-sap-v2"

    _act_as_store(client)
    forbidden = client.post(
        "/api/v1/admin/finance/stores/g5-store/sap-corrections",
        json={**payload, "readVersion": 2},
        headers={"Idempotency-Key": "g5-sap-correction-store"},
    )
    assert forbidden.status_code == 403


def test_finance_store_list_metrics_and_export_share_sap_discrepancy_contract(
    client: TestClient,
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    for store_id, statement_id in (
        ("g5-discrepancy-store", "g5-discrepancy-statement"),
        ("g5-aligned-store", "g5-aligned-statement"),
        ("g5-pending-store", "g5-pending-statement"),
    ):
        _seed_store_and_statement(
            db_session,
            store_id=store_id,
            statement_id=statement_id,
            sap_code_snapshot=f"SNAPSHOT-{store_id}",
        )
    db_session.add_all(
        [
            StoreFinanceProfile(
                profile_id="g5-discrepancy-finance-v1",
                store_id="g5-discrepancy-store",
                profile_type=1,
                source_type=3,
                version_no=1,
                is_current=True,
                store_name_snapshot="G5 Store",
                sap_code="SAP-FINANCE-A",
                created_at=now,
                updated_at=now,
            ),
            StoreFinanceProfile(
                profile_id="g5-aligned-finance-v1",
                store_id="g5-aligned-store",
                profile_type=1,
                source_type=3,
                version_no=1,
                is_current=True,
                store_name_snapshot="G5 Store",
                sap_code="SAP-ALIGNED-B",
                created_at=now,
                updated_at=now,
            ),
            StoreFinanceProfile(
                profile_id="g5-pending-finance-v1",
                store_id="g5-pending-store",
                profile_type=1,
                source_type=3,
                version_no=1,
                is_current=True,
                store_name_snapshot="G5 Store",
                sap_code="SAP-PENDING-C",
                created_at=now,
                updated_at=now,
            ),
            SapSuggestion(
                suggestion_id="g5-discrepancy-suggestion",
                store_id="g5-discrepancy-store",
                version_no=1,
                is_current=True,
                suggested_sap_code="SAP-STORE-A",
                suggestion_note="门店值与财务值不一致",
                suggestion_status=1,
                submitted_by="g5-discrepancy-user",
                submitted_at=now,
            ),
            SapSuggestion(
                suggestion_id="g5-aligned-suggestion",
                store_id="g5-aligned-store",
                version_no=1,
                is_current=True,
                suggested_sap_code="SAP-ALIGNED-B",
                suggestion_note="门店值与财务值一致",
                suggestion_status=2,
                submitted_by="g5-aligned-user",
                submitted_at=now,
                handled_by="finance-admin",
                handled_at=now,
            ),
        ]
    )
    db_session.commit()
    _login(client)
    params = {
        "month": "2026-08",
        "feeDirection": "PROMOTION",
        "metricScope": "MONTH",
        "pageSize": 50,
    }

    all_stores = client.get("/api/v1/admin/finance/stores", params=params)
    discrepancies = client.get(
        "/api/v1/admin/finance/stores",
        params={**params, "sapDiscrepanciesOnly": "true"},
    )
    exported = client.get(
        "/api/v1/admin/finance/stores/sap-discrepancies/export",
        params=params,
    )

    assert all_stores.status_code == 200
    all_payload = all_stores.json()["data"]
    assert all_payload["total"] == 3
    rows = {row["storeId"]: row for row in all_payload["list"]}
    assert rows["g5-discrepancy-store"]["sapStatus"] == (
        "FINANCE_ACTION_REQUIRED"
    )
    assert rows["g5-aligned-store"]["sapStatus"] == "CONFIRMED"
    assert rows["g5-pending-store"]["sapStatus"] == (
        "PENDING_STORE_CONFIRMATION"
    )
    assert all_payload["sapMetrics"] == {
        "discrepancyCount": 1,
        "pendingStoreConfirmationCount": 1,
        "financeActionableCount": 1,
        "confirmedTodayCount": 1,
    }

    assert discrepancies.status_code == 200
    discrepancy_payload = discrepancies.json()["data"]
    assert discrepancy_payload["total"] == 1
    assert [row["storeId"] for row in discrepancy_payload["list"]] == [
        "g5-discrepancy-store"
    ]
    discrepancy = discrepancy_payload["list"][0]
    assert discrepancy["discrepancyId"] == "g5-discrepancy-suggestion"
    assert discrepancy["storeMaintainedSapCode"] == "SAP-STORE-A"
    assert discrepancy["financeImportedSapCode"] == "SAP-FINANCE-A"
    assert discrepancy["effectiveSapCode"] == "SAP-FINANCE-A"
    assert discrepancy["discrepancyDetectedAt"] is not None
    assert discrepancy_payload["sapMetrics"] == all_payload["sapMetrics"]

    assert exported.status_code == 200
    exported_text = exported.content.decode("utf-8-sig")
    assert "store_maintained_sap_code" in exported_text.splitlines()[0]
    assert "finance_imported_sap_code" in exported_text.splitlines()[0]
    assert "g5-discrepancy-store" in exported_text
    assert "g5-aligned-store" not in exported_text
    assert "g5-pending-store" not in exported_text


def test_dispute_detection_job_persists_consistency_without_business_transition(
    client: TestClient,
    db_session: Session,
) -> None:
    statement = _seed_store_and_statement(db_session)
    db_session.add_all(
        [
            SettlementStatementEntry(
                statement_entry_id="g5-dispute-entry",
                statement_id=statement.statement_id,
                statement_line_id="g5-dispute-line",
                source_type=1,
                source_record_id="g5-dispute-source",
                original_fee_result_id="g5-dispute-fee",
                coupon_id="g5-dispute-coupon",
                order_id="g5-dispute-order",
                fee_direction=1,
                original_business_month="2026-08",
                statement_posting_month="2026-08",
                product_scope="LOCAL_LIFE",
                product_type="SERVICE_PRODUCT",
                base_amount_cent=1000,
                fee_amount_cent=100,
                rule_version="g5-rule-v1",
            ),
            SettlementDispute(
                dispute_id="g5-dispute",
                statement_id=statement.statement_id,
                store_id=statement.store_id,
                statement_month=statement.statement_month,
                fee_direction=1,
                dispute_type=3,
                status=1,
                disputed_amount_cent=100,
                description="核验数据库冻结分录",
                contact_name="门店联系人",
                contact_phone_ciphertext="invalid-test-ciphertext",
                evidence_json=[],
                submitted_by="g5-store-user",
                submitted_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
            ),
            SettlementDisputeOrder(
                dispute_id="g5-dispute",
                order_id="g5-dispute-order",
                coupon_id="g5-dispute-coupon",
                disputed_amount_cent=100,
            ),
        ]
    )
    db_session.commit()
    _login(client)

    started = client.post(
        "/api/v1/admin/disputes/g5-dispute/detections",
        headers={"Idempotency-Key": "g5-dispute-detection-0001"},
    )
    replayed = client.post(
        "/api/v1/admin/disputes/g5-dispute/detections",
        headers={"Idempotency-Key": "g5-dispute-detection-0001"},
    )

    assert started.status_code == 200
    assert replayed.status_code == 200
    job_id = started.json()["data"]["detectionId"]
    assert replayed.json()["data"]["detectionId"] == job_id
    db_session.expire_all()
    detail = client.get(
        f"/api/v1/admin/disputes/g5-dispute/detections/{job_id}"
    )
    latest = client.get(
        "/api/v1/admin/disputes/g5-dispute/detections/latest"
    )

    assert detail.status_code == 200
    job = detail.json()["data"]
    assert job["detectionId"] == job_id
    assert job["status"] == "SUCCEEDED"
    assert job["stage"] == "COMPLETED"
    assert job["progressPercent"] == 100
    assert job["resultSummary"] == "正式数据库一致性检查通过"
    assert job["checks"]["linkedOrderScope"] is True
    assert job["checks"]["disputedAmountSum"] is True
    assert {
        item["evidenceType"] for item in job["evidence"]
    } == {
        "SUBMITTED_STATEMENT",
        "CURRENT_STATEMENT",
        "DISPUTE_ORDER_SCOPE",
    }
    assert job["failureReason"] is None
    assert job["completedAt"] is not None
    assert job["updatedAt"] == job["completedAt"]
    assert "jobId" not in job
    assert "progress" not in job
    assert "result" not in job
    assert "finishedAt" not in job
    assert latest.status_code == 200
    assert latest.json()["data"]["detectionId"] == job_id
    assert db_session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.job_name == "finance_dispute_detection")
    ) == 1
    stored_job = db_session.get(JobRun, job_id)
    assert stored_job is not None
    stored_result = stored_job.metadata_json["result"]
    assert stored_result["consistencyStatus"] == "CONSISTENT"
    assert stored_result["checks"]["linkedOrderScope"] is True
    assert stored_result["checks"]["disputedAmountSum"] is True
    assert stored_result["checks"]["submittedStatementSnapshot"] is True
    assert stored_result["checks"]["currentStatementVersion"] is True
    dispute = db_session.scalar(
        select(SettlementDispute).where(
            SettlementDispute.dispute_id == "g5-dispute"
        )
    )
    assert dispute is not None
    assert dispute.status == 1

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            SettlementDispute(
                dispute_id="g5-dispute-running",
                statement_id=statement.statement_id,
                store_id=statement.store_id,
                statement_month=statement.statement_month,
                fee_direction=1,
                dispute_type=1,
                status=2,
                disputed_amount_cent=50,
                description="正在检测的费率异议",
                contact_name="门店联系人",
                contact_phone_ciphertext="invalid-test-ciphertext",
                evidence_json=[],
                submitted_by="g5-store-user",
                submitted_at=now,
            ),
            SettlementDispute(
                dispute_id="g5-dispute-completed",
                statement_id=statement.statement_id,
                store_id=statement.store_id,
                statement_month=statement.statement_month,
                fee_direction=1,
                dispute_type=4,
                status=5,
                disputed_amount_cent=10,
                description="今日已完成异议",
                contact_name="门店联系人",
                contact_phone_ciphertext="invalid-test-ciphertext",
                evidence_json=[],
                submitted_by="g5-store-user",
                submitted_at=now,
                processed_by="finance-admin",
                processed_at=now,
            ),
            JobRun(
                job_id="g5-running-detection",
                job_name="finance_dispute_detection",
                status="running",
                started_at=now,
                state_updated_at=now,
                success_count=0,
                failed_count=0,
                metadata_json={
                    "disputeId": "g5-dispute-running",
                    "requestedBy": "system-admin",
                    "stage": "EVALUATING_CONSISTENCY",
                    "progress": 40,
                    "result": None,
                    "failureReason": None,
                },
            ),
        ]
    )
    db_session.commit()

    listed = client.get("/api/v1/admin/disputes")
    assert listed.status_code == 200
    list_payload = listed.json()["data"]
    assert list_payload["metrics"] == {
        "amountDisputeCount": 1,
        "detectingCount": 1,
        "pendingAdminCount": 2,
        "completedTodayCount": 1,
    }
    list_rows = {row["disputeId"]: row for row in list_payload["list"]}
    assert list_rows["g5-dispute"]["storeName"] == "G5 Store"
    assert list_rows["g5-dispute"]["latestDetection"]["detectionId"] == job_id
    assert list_rows["g5-dispute-running"]["latestDetection"] == {
        "detectionId": "g5-running-detection",
        "disputeId": "g5-dispute-running",
        "status": "RUNNING",
        "stage": "EVALUATING_CONSISTENCY",
        "progressPercent": 40,
        "resultSummary": None,
        "checks": {},
        "evidence": [],
        "failureReason": None,
        "startedAt": now.isoformat(),
        "completedAt": None,
        "updatedAt": now.isoformat(),
    }


def test_sap_confirmation_bulk_import_updates_type_one_effective_sap_without_rewriting_snapshot(
    client: TestClient,
    db_session: Session,
) -> None:
    statement = _seed_store_and_statement(
        db_session, sap_code_snapshot="SAP-HISTORICAL-SNAPSHOT"
    )
    db_session.add_all(
        [
            StoreFinanceProfile(
                profile_id="g5-bulk-finance-v1",
                store_id="g5-store",
                profile_type=1,
                source_type=1,
                version_no=1,
                is_current=True,
                store_name_snapshot="G5 Store",
                sap_code="SAP-FINANCE-001",
                created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
                updated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            ),
            SapSuggestion(
                suggestion_id="g5-bulk-store-suggestion-v1",
                store_id="g5-store",
                version_no=1,
                is_current=True,
                suggested_sap_code="SAP-STORE-DIFFERENT-008",
                suggestion_note="批量最终确认前的门店建议",
                suggestion_status=1,
                submitted_by="g5-store-user",
                submitted_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
            ),
        ]
    )
    db_session.commit()
    _login(client)
    content = (
        "storeId,storeName,financeInitialSap,serviceStoreCode,finalSapCode,"
        "factoryConfirmationResult,confirmedAt\n"
        "g5-store,G5 Store,SAP-FINANCE-001,SVC-G5,SAP-FINAL-009,"
        "CONFIRMED,2026-08-30T10:00:00+08:00\n"
    )

    uploaded = client.post(
        "/api/v1/admin/finance-imports",
        data={"importType": "SAP_CONFIRMATION", "statementMonth": "2026-08"},
        files={
            "file": (
                "sap-confirmation.csv",
                content.encode("utf-8"),
                "text/csv",
            )
        },
        headers={"Idempotency-Key": "g5-sap-bulk-upload-0001"},
    )
    assert uploaded.status_code == 200
    batch = uploaded.json()["data"]
    committed = client.post(
        f"/api/v1/admin/finance-imports/{batch['batchId']}/commits",
        json={
            "readVersion": batch["readVersion"],
            "changeReason": "厂家确认最终有效 SAP",
        },
        headers={"Idempotency-Key": "g5-sap-bulk-commit-0001"},
    )

    assert committed.status_code == 200
    profiles = list(
        db_session.scalars(
            select(StoreFinanceProfile)
            .where(StoreFinanceProfile.store_id == "g5-store")
            .order_by(
                StoreFinanceProfile.profile_type,
                StoreFinanceProfile.version_no,
            )
        )
    )
    assert [profile.profile_type for profile in profiles] == [1, 1]
    assert [profile.version_no for profile in profiles] == [1, 2]
    assert [profile.is_current for profile in profiles] == [False, True]
    current = profiles[-1]
    assert current.sap_code == "SAP-FINAL-009"
    assert current.initial_sap_code == "SAP-FINANCE-001"
    assert current.service_store_code == "SVC-G5"
    assert current.factory_confirmed is True
    assert current.confirmed_at is not None

    listed = client.get(
        "/api/v1/admin/finance/stores",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )
    assert listed.status_code == 200
    row = listed.json()["data"]["list"][0]
    assert row["financeImportedSapCode"] == "SAP-FINAL-009"
    assert row["effectiveSapCode"] == "SAP-FINAL-009"
    assert row["effectiveSapVersion"] == 2
    assert row["effectiveSapUpdatedBy"] == "system-admin"
    assert row["storeMaintainedSapCode"] == "SAP-STORE-DIFFERENT-008"
    assert row["sapStatus"] == "CONFIRMED"
    assert row["discrepancyId"] is None
    assert db_session.scalar(
        select(func.count())
        .select_from(FinanceOperationAudit)
        .where(
            FinanceOperationAudit.operation_type == "FINANCE_IMPORT_COMMIT",
            FinanceOperationAudit.result_status == 1,
        )
    ) == 1
    db_session.refresh(statement)
    assert statement.sap_code_snapshot == "SAP-HISTORICAL-SNAPSHOT"

    prior_suggestion = db_session.scalar(
        select(SapSuggestion).where(
            SapSuggestion.suggestion_id == "g5-bulk-store-suggestion-v1"
        )
    )
    assert prior_suggestion is not None
    prior_suggestion.is_current = False
    imported_at = current.updated_at
    if imported_at.tzinfo is None:
        imported_at = imported_at.replace(tzinfo=timezone.utc)
    db_session.add(
        SapSuggestion(
            suggestion_id="g5-bulk-store-suggestion-v2",
            store_id="g5-store",
            version_no=2,
            is_current=True,
            suggested_sap_code="SAP-STORE-NEW-010",
            suggestion_note="批量最终确认后的门店新建议",
            suggestion_status=1,
            submitted_by="g5-store-user",
            submitted_at=imported_at + timedelta(seconds=1),
        )
    )
    db_session.commit()
    reopened = client.get(
        "/api/v1/admin/finance/stores",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
        },
    )
    assert reopened.status_code == 200
    reopened_row = reopened.json()["data"]["list"][0]
    assert reopened_row["sapStatus"] == "FINANCE_ACTION_REQUIRED"
    assert reopened_row["discrepancyId"] == "g5-bulk-store-suggestion-v2"
    db_session.refresh(statement)
    assert statement.sap_code_snapshot == "SAP-HISTORICAL-SNAPSHOT"


def test_finance_import_templates_are_real_header_only_files(
    client: TestClient,
) -> None:
    _login(client)
    expected_headers = {
        "BASIC_INFO": "storeId,storeName,sapCode,importedAt",
        "PROMOTION_FACTORY_RESULT": (
            "invoiceNumber,reviewResult,rejectionReason,settlementDate,"
            "settlementAmountCent"
        ),
        "MANAGEMENT_FACTORY_RESULT": (
            "storeId,statementMonth,storeName,invoiceNumber,invoiceDate,"
            "deductionDate,deductionAmountCent"
        ),
        "SAP_CONFIRMATION": (
            "storeId,storeName,financeInitialSap,serviceStoreCode,finalSapCode,"
            "factoryConfirmationResult,confirmedAt"
        ),
    }

    for import_type, expected_header in expected_headers.items():
        response = client.get(
            f"/api/v1/admin/finance-imports/templates/{import_type}"
        )
        assert response.status_code == 200
        assert response.content.startswith(b"\xef\xbb\xbf")
        assert response.headers["content-type"].startswith("text/csv")
        assert response.content.decode("utf-8-sig").splitlines() == [
            expected_header
        ]


def test_finance_contract_exports_are_header_only_when_no_official_rows_exist(
    client: TestClient,
) -> None:
    _login(client)
    endpoints = (
        (
            "/api/v1/admin/finance/invoices/export",
            {"month": "2026-08", "feeDirection": "PROMOTION"},
        ),
        (
            "/api/v1/admin/finance/stores/export",
            {
                "month": "2026-08",
                "feeDirection": "PROMOTION",
                "metricScope": "MONTH",
            },
        ),
        (
            "/api/v1/admin/finance/stores/sap-discrepancies/export",
            {
                "month": "2026-08",
                "feeDirection": "PROMOTION",
                "metricScope": "MONTH",
            },
        ),
        ("/api/v1/admin/disputes/export", {}),
    )

    for endpoint, params in endpoints:
        response = client.get(endpoint, params=params)
        assert response.status_code == 200
        assert response.content.startswith(b"\xef\xbb\xbf")
        assert response.headers["content-type"].startswith("text/csv")
        lines = response.content.decode("utf-8-sig").splitlines()
        assert len(lines) == 1
        assert "," in lines[0]


def test_finance_pages_use_independent_stable_page_keys(
    client: TestClient,
) -> None:
    _act_as_restricted_finance_admin(
        client,
        store_ids=(),
        page_keys=("FIN01",),
    )
    common = {
        "month": "2026-08",
        "metricScope": "MONTH",
    }

    promotion = client.get(
        "/api/v1/admin/finance/summary",
        params={**common, "feeDirection": "PROMOTION"},
    )
    management = client.get(
        "/api/v1/admin/finance/summary",
        params={**common, "feeDirection": "MANAGEMENT"},
    )
    orders = client.get(
        "/api/v1/admin/finance/order-details",
        params={"month": "2026-08", "feeDirection": "PROMOTION"},
    )
    stores = client.get(
        "/api/v1/admin/finance/stores",
        params={**common, "feeDirection": "PROMOTION"},
    )
    disputes = client.get("/api/v1/admin/disputes")
    imports = client.get("/api/v1/admin/finance-imports")

    assert promotion.status_code == 200
    for response, page_key in (
        (management, "FIN02"),
        (orders, "FIN03"),
        (stores, "FIN04"),
        (disputes, "FIN05"),
        (imports, "FIN06"),
    ):
        assert response.status_code == 403
        assert page_key in str(response.json()["detail"])


def test_restricted_finance_admin_queries_exports_and_writes_stay_in_store_scope(
    client: TestClient,
    db_session: Session,
) -> None:
    assigned = _seed_store_and_statement(
        db_session,
        store_id="g5-scope-a",
        statement_id="g5-scope-a-statement",
        promotion_amount_cent=1100,
    )
    denied = _seed_store_and_statement(
        db_session,
        store_id="g5-scope-b",
        statement_id="g5-scope-b-statement",
        promotion_amount_cent=2200,
    )
    for statement, suffix in ((assigned, "a"), (denied, "b")):
        db_session.add_all(
            [
                SettlementStatementConfirmation(
                    confirmation_id=f"g5-scope-{suffix}-confirmation",
                    statement_id=statement.statement_id,
                    fee_direction=1,
                    confirmation_status=1,
                    confirmed_amount_cent=statement.promotion_net_fee_cent,
                    confirmed_by=f"g5-scope-{suffix}-store-user",
                    confirmed_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
                ),
                SettlementStatementEntry(
                    statement_entry_id=f"g5-scope-{suffix}-entry",
                    statement_id=statement.statement_id,
                    statement_line_id=f"g5-scope-{suffix}-line",
                    source_type=1,
                    source_record_id=f"g5-scope-{suffix}-source",
                    original_fee_result_id=f"g5-scope-{suffix}-fee",
                    order_id=f"g5-scope-{suffix}-order",
                    coupon_id=f"g5-scope-{suffix}-coupon",
                    fee_direction=1,
                    original_business_month="2026-08",
                    statement_posting_month="2026-08",
                    product_scope="LOCAL_LIFE",
                    product_type="SERVICE_PRODUCT",
                    base_amount_cent=10_000,
                    fee_amount_cent=statement.promotion_net_fee_cent,
                    rule_version="g5-scope-rule-v1",
                ),
                SettlementDispute(
                    dispute_id=f"g5-scope-{suffix}-dispute",
                    statement_id=statement.statement_id,
                    store_id=statement.store_id,
                    statement_month=statement.statement_month,
                    fee_direction=1,
                    dispute_type=3,
                    status=1,
                    disputed_amount_cent=100,
                    description=f"scope {suffix}",
                    contact_name="Scope Contact",
                    contact_phone_ciphertext="invalid-test-ciphertext",
                    evidence_json=[],
                    submitted_by=f"g5-scope-{suffix}-store-user",
                    submitted_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
                ),
                SettlementDisputeOrder(
                    dispute_id=f"g5-scope-{suffix}-dispute",
                    order_id=f"g5-scope-{suffix}-order",
                    coupon_id=f"g5-scope-{suffix}-coupon",
                    disputed_amount_cent=100,
                ),
            ]
        )
    db_session.commit()
    _seed_promotion_invoice(
        db_session,
        statement=assigned,
        invoice_id="g5-scope-a-invoice",
        invoice_number="75345678901234567890",
        invoice_amount_cent=1100,
    )
    _seed_promotion_invoice(
        db_session,
        statement=denied,
        invoice_id="g5-scope-b-invoice",
        invoice_number="76345678901234567890",
        invoice_amount_cent=2200,
    )
    for suffix, store_id in (("a", "g5-scope-a"), ("b", "g5-scope-b")):
        batch = FinanceImportBatch(
            batch_id=f"g5-scope-{suffix}-batch",
            import_type=1,
            statement_month="2026-08",
            file_name=f"scope-{suffix}.csv",
            file_sha256=suffix * 64,
            normalized_sha256=("c" if suffix == "a" else "d") * 64,
            read_version=0,
            current_version=0,
            batch_status=6,
            total_rows=1,
            success_rows=0,
            error_rows=1,
            content_changed=False,
            submitted_by="scope-admin",
        )
        db_session.add_all(
            [
                batch,
                FinanceImportRow(
                    batch_id=batch.batch_id,
                    row_number=2,
                    business_key=store_id,
                    normalized_payload={"storeId": store_id},
                    row_status=4,
                    validation_errors=[],
                ),
            ]
        )
    db_session.commit()

    _act_as_restricted_finance_admin(client, store_ids=("g5-scope-a",))
    common = {
        "month": "2026-08",
        "feeDirection": "PROMOTION",
        "metricScope": "MONTH",
    }
    summary = client.get("/api/v1/admin/finance/summary", params=common)
    invoices = client.get("/api/v1/admin/finance/invoices", params=common)
    invoice_export = client.get(
        "/api/v1/admin/finance/invoices/export", params=common
    )
    orders = client.get(
        "/api/v1/admin/finance/order-details",
        params={"month": "2026-08", "feeDirection": "PROMOTION"},
    )
    order_export = client.get(
        "/api/v1/admin/finance/order-details/export",
        params={"month": "2026-08", "feeDirection": "PROMOTION"},
    )
    stores = client.get("/api/v1/admin/finance/stores", params=common)
    store_export = client.get(
        "/api/v1/admin/finance/stores/export", params=common
    )
    disputes = client.get("/api/v1/admin/disputes")
    dispute_export = client.get("/api/v1/admin/disputes/export")
    imports = client.get("/api/v1/admin/finance-imports")

    assert summary.json()["data"]["metrics"]["statementTotalCent"] == 1100
    assert [row["storeId"] for row in invoices.json()["data"]["list"]] == [
        "g5-scope-a"
    ]
    assert "g5-scope-a" in invoice_export.text
    assert "g5-scope-b" not in invoice_export.text
    assert [row["storeId"] for row in orders.json()["data"]["list"]] == [
        "g5-scope-a"
    ]
    assert "g5-scope-a" in order_export.text
    assert "g5-scope-b" not in order_export.text
    assert [row["storeId"] for row in stores.json()["data"]["list"]] == [
        "g5-scope-a"
    ]
    assert "g5-scope-a" in store_export.text
    assert "g5-scope-b" not in store_export.text
    assert [row["storeId"] for row in disputes.json()["data"]["list"]] == [
        "g5-scope-a"
    ]
    assert "g5-scope-a" in dispute_export.text
    assert "g5-scope-b" not in dispute_export.text
    assert [row["batchId"] for row in imports.json()["data"]["list"]] == [
        "g5-scope-a-batch"
    ]
    assert client.get(
        "/api/v1/admin/finance-imports/g5-scope-b-batch"
    ).status_code == 403
    assert client.get(
        "/api/v1/admin/finance/summary",
        params={**common, "storeId": "g5-scope-b"},
    ).status_code == 403
    assert client.post(
        "/api/v1/admin/disputes/g5-scope-b-dispute/detections",
        headers={"Idempotency-Key": "g5-scope-denied-detect-0001"},
    ).status_code == 403
    assert client.post(
        "/api/v1/admin/finance/stores/g5-scope-b/sap-corrections",
        json={
            "finalSapCode": "SAP-DENIED",
            "changeReason": "must stay denied",
            "readVersion": 0,
        },
        headers={"Idempotency-Key": "g5-scope-denied-sap-0001"},
    ).status_code == 403


def test_restricted_finance_import_validates_every_row_against_store_scope(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_store_and_statement(
        db_session,
        store_id="g5-import-scope-a",
        statement_id="g5-import-scope-a-statement",
    )
    _seed_store_and_statement(
        db_session,
        store_id="g5-import-scope-b",
        statement_id="g5-import-scope-b-statement",
    )
    _act_as_restricted_finance_admin(
        client,
        store_ids=("g5-import-scope-a",),
        page_keys=("FIN04",),
    )
    content = (
        "storeId,storeName,sapCode,importedAt\n"
        "g5-import-scope-a,G5 Store,SAP-A,2026-08-30T10:00:00+08:00\n"
        "g5-import-scope-b,G5 Store,SAP-B,2026-08-30T10:00:00+08:00\n"
    )

    uploaded = client.post(
        "/api/v1/admin/finance-imports",
        data={"importType": "BASIC_INFO", "statementMonth": "2026-08"},
        files={"file": ("scope.csv", content.encode("utf-8"), "text/csv")},
        headers={"Idempotency-Key": "g5-import-scope-upload-0001"},
    )

    assert uploaded.status_code == 200
    data = uploaded.json()["data"]
    assert data["scenario"] == "BATCH_VALIDATION_FAILED"
    assert any(
        error["rowNumber"] == 3
        and error["field"] == "storeId"
        and "授权范围" in error["reason"]
        for error in data["errors"]["list"]
    )
    committed = client.post(
        f"/api/v1/admin/finance-imports/{data['batchId']}/commits",
        json={"readVersion": data["readVersion"], "changeReason": "scope test"},
        headers={"Idempotency-Key": "g5-import-scope-commit-0001"},
    )
    assert committed.status_code in {403, 409}
    assert db_session.scalar(
        select(func.count()).select_from(StoreFinanceProfile)
    ) == 0


def test_legacy_type_two_sap_accepts_first_type_one_correction_and_replay_is_immutable(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_store_and_statement(db_session)
    db_session.add(
        StoreFinanceProfile(
            profile_id="g5-legacy-only-v4",
            store_id="g5-store",
            profile_type=2,
            source_type=2,
            version_no=4,
            is_current=True,
            store_name_snapshot="G5 Store",
            sap_code="SAP-LEGACY-004",
            factory_confirmed=True,
            confirmed_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
            created_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
            updated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    _login(client)
    first_payload = {
        "finalSapCode": "SAP-FINANCE-FIRST",
        "changeReason": "建立财务控制链",
        "readVersion": 4,
    }
    first = client.post(
        "/api/v1/admin/finance/stores/g5-store/sap-corrections",
        json=first_payload,
        headers={"Idempotency-Key": "g5-legacy-first-correction"},
    )

    assert first.status_code == 200
    first_data = first.json()["data"]
    assert first_data["effectiveSapCode"] == "SAP-FINANCE-FIRST"
    assert first_data["effectiveSapVersion"] == 1
    second = client.post(
        "/api/v1/admin/finance/stores/g5-store/sap-corrections",
        json={
            "finalSapCode": "SAP-FINANCE-SECOND",
            "changeReason": "第二次财务矫正",
            "readVersion": 1,
        },
        headers={"Idempotency-Key": "g5-legacy-second-correction"},
    )
    replay = client.post(
        "/api/v1/admin/finance/stores/g5-store/sap-corrections",
        json=first_payload,
        headers={"Idempotency-Key": "g5-legacy-first-correction"},
    )

    assert second.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["data"] == first_data


def test_finance_sap_tombstone_uses_its_control_version_for_single_correction(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_store_and_statement(db_session)
    observed_at = datetime(2026, 8, 20, tzinfo=timezone.utc)
    db_session.add_all(
        [
            StoreFinanceProfile(
                profile_id="g5-legacy-current-v4",
                store_id="g5-store",
                profile_type=2,
                source_type=2,
                version_no=4,
                is_current=True,
                is_tombstone=False,
                store_name_snapshot="G5 Store",
                sap_code="SAP-LEGACY-004",
                created_at=observed_at,
                updated_at=observed_at,
            ),
            StoreFinanceProfile(
                profile_id="g5-finance-tombstone-v2",
                store_id="g5-store",
                profile_type=1,
                source_type=3,
                version_no=2,
                is_current=True,
                is_tombstone=True,
                store_name_snapshot="G5 Store",
                sap_code=None,
                created_at=observed_at,
                updated_at=observed_at,
            ),
        ]
    )
    db_session.commit()
    _login(client)

    response = client.get(
        "/api/v1/admin/finance/stores",
        params={
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "metricScope": "MONTH",
            "q": "g5-store",
        },
    )

    assert response.status_code == 200
    row = response.json()["data"]["list"][0]
    assert row["effectiveSapCode"] is None
    assert row["effectiveSapVersion"] == 2

    corrected = client.post(
        "/api/v1/admin/finance/stores/g5-store/sap-corrections",
        json={
            "finalSapCode": "SAP-FINANCE-RESTORED",
            "changeReason": "从财务控制链 tombstone 恢复",
            "readVersion": row["effectiveSapVersion"],
        },
        headers={"Idempotency-Key": "g5-finance-tombstone-correction"},
    )

    assert corrected.status_code == 200
    assert corrected.json()["data"]["effectiveSapCode"] == "SAP-FINANCE-RESTORED"
    assert corrected.json()["data"]["effectiveSapVersion"] == 3
