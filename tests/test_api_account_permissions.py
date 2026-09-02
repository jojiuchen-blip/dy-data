from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import (  # noqa: E402
    AggStoreMonthlySettlement,
    DimStore,
    RawDouyinOrder,
    RawDouyinOrderCoupon,
    SettlementFeeAdjustment,
    SettlementFeeResult,
    SettlementFeeResultCurrent,
    SettlementOrderDetail,
    SettlementStatement,
    SettlementStatementEntry,
    SettlementStatementLine,
    User,
    UserStoreScope,
)
from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import DashboardDataStore, get_session_dependency  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    _seed(db_session)
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _seed(session: Session) -> None:
    timestamp = datetime(2026, 5, 1, 8, tzinfo=timezone.utc)
    session.add_all(
        [
            RawDouyinOrder(
                order_id="order-fee-own",
                order_status_normalized="PAID",
                sku_id="sku",
                product_name="Product",
                sale_time=timestamp,
                order_paid_amount_cent=1000,
                sale_channel_normalized="LIVE",
            ),
            RawDouyinOrder(
                order_id="order-fee-other",
                order_status_normalized="PAID",
                sku_id="sku",
                product_name="Product",
                sale_time=timestamp,
                order_paid_amount_cent=1000,
                sale_channel_normalized="LIVE",
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            DimStore(store_id="store-1", store_name="Store One", is_active=True),
            DimStore(store_id="store-2", store_name="Store Two", is_active=True),
            DimStore(store_id="store-3", store_name="Store Three", is_active=True),
            User(
                user_id="store-user",
                username="store-user",
                external_account_id="store-1",
                display_name="Store User",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("secret"),
            ),
            User(
                user_id="viewer-user",
                username="viewer-user",
                external_account_id=None,
                display_name="Viewer User",
                role="viewer",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("secret"),
            ),
            User(
                user_id="empty-store-user",
                username="empty-store-user",
                external_account_id=None,
                display_name="Empty Store User",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("secret"),
            ),
            UserStoreScope(user_id="store-user", store_id="store-1"),
            AggStoreMonthlySettlement(
                month="2026-05",
                product_type="all",
                store_id="store-1",
                estimated_receivable_commission_cent=100,
                commissionable_total_cent=1000,
                estimated_payable_commission_cent=0,
                updated_at=timestamp,
            ),
            AggStoreMonthlySettlement(
                month="2026-05",
                product_type="all",
                store_id="store-2",
                estimated_receivable_commission_cent=200,
                commissionable_total_cent=2000,
                estimated_payable_commission_cent=0,
                updated_at=timestamp,
            ),
            SettlementOrderDetail(
                coupon_id="coupon-sale",
                order_id="order-sale",
                sku_id="sku",
                owner_account_id="owner",
                owner_account_name="Owner",
                product_type="all",
                sale_store_id="store-1",
                sale_store_name="Store One",
                sale_time=timestamp,
                is_verified=True,
                verify_store_id="store-2",
                verify_store_name="Store Two",
                verify_time=timestamp,
                relation_type="cross_store",
                is_commissionable=True,
                is_refund_excluded=False,
                paid_amount_cent=1000,
                commission_rate=Decimal("0.1000"),
                receivable_commission_cent=100,
                payable_commission_cent=100,
                source_run_id="test",
                updated_at=timestamp,
            ),
            SettlementOrderDetail(
                coupon_id="coupon-other",
                order_id="order-other",
                sku_id="sku",
                owner_account_id="owner",
                owner_account_name="Owner",
                product_type="all",
                sale_store_id="store-2",
                sale_store_name="Store Two",
                sale_time=timestamp,
                is_verified=False,
                relation_type="unverified",
                is_commissionable=True,
                is_refund_excluded=False,
                paid_amount_cent=1000,
                commission_rate=Decimal("0.1000"),
                receivable_commission_cent=0,
                payable_commission_cent=0,
                source_run_id="test",
                updated_at=timestamp,
            ),
            RawDouyinOrderCoupon(
                coupon_id="coupon-fee-own",
                order_id="order-fee-own",
                coupon_status_normalized="VERIFIED",
                coupon_paid_amount_cent=1000,
                coupon_refunded_amount_cent=0,
            ),
            RawDouyinOrderCoupon(
                coupon_id="coupon-fee-other",
                order_id="order-fee-other",
                coupon_status_normalized="VERIFIED",
                coupon_paid_amount_cent=1000,
                coupon_refunded_amount_cent=0,
            ),
            SettlementFeeResult(
                fee_result_id="fee-own",
                coupon_id="coupon-fee-own",
                order_id="order-fee-own",
                fee_direction=1,
                result_version=1,
                original_business_month="2026-05",
                rule_match_date=date(2026, 5, 1),
                sale_store_id="store-1",
                verify_store_id="store-2",
                sku_id="sku",
                product_scope="all",
                product_type="all",
                sale_channel_normalized="LIVE",
                source_amount_cent=1000,
                refunded_amount_cent=0,
                fee_base_cent=1000,
                fee_rate=Decimal("0.100000"),
                fee_amount_cent=100,
                rule_version="rule-v1",
                scope_rule_version="scope-v1",
                result_status=1,
                calculation_run_id="run-1",
                calculated_at=timestamp,
            ),
            SettlementFeeResultCurrent(
                coupon_id="coupon-fee-own",
                fee_direction=1,
                fee_result_id="fee-own",
            ),
            SettlementFeeResult(
                fee_result_id="fee-other",
                coupon_id="coupon-fee-other",
                order_id="order-fee-other",
                fee_direction=1,
                result_version=1,
                original_business_month="2026-05",
                rule_match_date=date(2026, 5, 1),
                sale_store_id="store-2",
                verify_store_id="store-1",
                sku_id="sku",
                product_scope="all",
                product_type="all",
                sale_channel_normalized="LIVE",
                source_amount_cent=1000,
                refunded_amount_cent=0,
                fee_base_cent=1000,
                fee_rate=Decimal("0.100000"),
                fee_amount_cent=100,
                rule_version="rule-v1",
                scope_rule_version="scope-v1",
                result_status=1,
                calculation_run_id="run-1",
                calculated_at=timestamp,
            ),
            SettlementFeeResultCurrent(
                coupon_id="coupon-fee-other",
                fee_direction=1,
                fee_result_id="fee-other",
            ),
            SettlementFeeResult(
                fee_result_id="fee-management-own",
                coupon_id="coupon-fee-own",
                order_id="order-fee-own",
                fee_direction=2,
                result_version=1,
                original_business_month="2026-05",
                rule_match_date=date(2026, 5, 1),
                sale_store_id="store-1",
                verify_store_id="store-2",
                sku_id="sku",
                product_scope="all",
                product_type="all",
                sale_channel_normalized="LIVE",
                source_amount_cent=1000,
                refunded_amount_cent=0,
                fee_base_cent=1000,
                fee_rate=Decimal("0.050000"),
                fee_amount_cent=50,
                rule_version="rule-v1",
                scope_rule_version="scope-v1",
                result_status=1,
                calculation_run_id="run-1",
                calculated_at=timestamp,
            ),
            SettlementFeeResultCurrent(
                coupon_id="coupon-fee-own",
                fee_direction=2,
                fee_result_id="fee-management-own",
            ),
            SettlementFeeResult(
                fee_result_id="fee-management-other",
                coupon_id="coupon-fee-other",
                order_id="order-fee-other",
                fee_direction=2,
                result_version=1,
                original_business_month="2026-05",
                rule_match_date=date(2026, 5, 1),
                sale_store_id="store-2",
                verify_store_id="store-1",
                sku_id="sku",
                product_scope="all",
                product_type="all",
                sale_channel_normalized="LIVE",
                source_amount_cent=1000,
                refunded_amount_cent=0,
                fee_base_cent=1000,
                fee_rate=Decimal("0.050000"),
                fee_amount_cent=50,
                rule_version="rule-v1",
                scope_rule_version="scope-v1",
                result_status=1,
                calculation_run_id="run-1",
                calculated_at=timestamp,
            ),
            SettlementFeeResultCurrent(
                coupon_id="coupon-fee-other",
                fee_direction=2,
                fee_result_id="fee-management-other",
            ),
            SettlementStatement(
                statement_id="statement-own",
                store_id="store-1",
                statement_month="2026-05",
                statement_status=4,
                promotion_original_fee_cent=100,
                promotion_adjustment_fee_cent=0,
                promotion_net_fee_cent=100,
                management_original_fee_cent=0,
                management_adjustment_fee_cent=0,
                management_net_fee_cent=0,
                locked_at=timestamp,
                lock_version="lock-v1",
            ),
            SettlementStatementLine(
                statement_line_id="line-own",
                statement_id="statement-own",
                fee_direction=1,
                product_scope="all",
                product_type="all",
                original_entry_count=1,
                adjustment_entry_count=0,
                original_base_cent=1000,
                adjustment_base_cent=0,
                net_base_cent=1000,
                original_fee_cent=100,
                adjustment_fee_cent=0,
                net_fee_cent=100,
            ),
            SettlementStatementEntry(
                statement_entry_id="entry-own",
                statement_id="statement-own",
                statement_line_id="line-own",
                source_type=1,
                source_record_id="fee-own",
                original_fee_result_id="fee-own",
                coupon_id="coupon-fee-own",
                order_id="order-fee-own",
                fee_direction=1,
                original_business_month="2026-05",
                statement_posting_month="2026-05",
                product_scope="all",
                product_type="all",
                base_amount_cent=1000,
                fee_amount_cent=100,
                rule_version="rule-v1",
            ),
            SettlementFeeAdjustment(
                adjustment_id="adjustment-after-lock",
                original_fee_result_id="fee-own",
                refund_event_id=None,
                coupon_id="coupon-fee-own",
                order_id="order-fee-own",
                fee_direction=1,
                original_business_month="2026-05",
                adjustment_posting_month="2026-06",
                adjustment_type=1,
                adjustment_base_cent=-100,
                adjustment_fee_cent=-10,
                rule_version="rule-v1",
                adjustment_reason="锁账后退款",
                occurred_at=datetime(2026, 6, 1, 8, tzinfo=timezone.utc),
                created_by="test",
            ),
        ]
    )
    session.commit()


def _login_store(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "store-user", "password": "secret"},
    )
    assert response.status_code == 200


def _login_viewer(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer-user", "password": "secret"},
    )
    assert response.status_code == 200


def _login_empty_store(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "empty-store-user", "password": "secret"},
    )
    assert response.status_code == 200


def test_store_user_permissions_are_enforced(client: TestClient) -> None:
    assert client.get("/api/v1/order-details").status_code == 401
    _login_store(client)

    own_store = client.get("/api/v1/stores/store-1/monthly-settlement?month=2026-05")
    assert own_store.status_code == 200
    own_settlement = own_store.json()["data"]
    assert own_settlement["statement"]["statementStatus"] == "LOCKED"
    assert own_settlement["lines"][0]["statementLineId"] == "line-own"
    assert own_settlement["lines"][0]["feeRates"] == ["0.100000"]
    assert own_settlement["lines"][0]["ruleVersions"] == ["rule-v1"]

    other_store = client.get("/api/v1/stores/store-2/monthly-settlement?month=2026-05")
    assert other_store.status_code == 403

    own_invoice_status = client.get(
        "/api/v1/store-invoice-status",
        params={"storeId": "store-1", "month": "2026-05"},
    )
    assert own_invoice_status.status_code == 200

    other_invoice_status = client.get(
        "/api/v1/store-invoice-status",
        params={"storeId": "store-2", "month": "2026-05"},
    )
    assert other_invoice_status.status_code == 403

    sales_without_store = client.get("/api/v1/dashboard/sales?month=2026-05")
    assert sales_without_store.status_code == 403

    own_sales = client.get(
        "/api/v1/dashboard/sales?store_id=store-1&month=2026-05&trend_months=2026-05"
    )
    assert own_sales.status_code == 200
    assert own_sales.json()["data"]["store"]["store_id"] == "store-1"

    details = client.get("/api/v1/order-details?page=1&page_size=50")
    assert details.status_code == 200
    rows = details.json()["data"]["rows"]
    assert [row["order_id"] for row in rows] == ["order-sale"]

    fee_details = client.get(
        "/api/v1/order-fee-details",
        params={
            "storeId": "store-1",
            "month": "2026-05",
            "feeDirection": "PROMOTION",
        },
    )
    assert fee_details.status_code == 200
    assert [row["orderId"] for row in fee_details.json()["data"]["list"]] == [
        "order-fee-own"
    ]

    direct_fee_details = client.get(
        "/api/v1/order-fee-details",
        params={"feeDirection": "PROMOTION"},
    )
    assert direct_fee_details.status_code == 200
    assert [
        row["orderId"] for row in direct_fee_details.json()["data"]["list"]
    ] == ["order-fee-own"]

    direct_fee_export = client.get(
        "/api/v1/order-fee-details/export",
        params={"feeDirection": "PROMOTION"},
    )
    assert direct_fee_export.status_code == 200
    direct_export_text = direct_fee_export.content.decode("utf-8-sig")
    assert "order-fee-own" in direct_export_text
    assert "order-fee-other" not in direct_export_text

    stale_direct = client.get(
        "/api/v1/order-fee-details",
        params=[
            ("feeDirection", "PROMOTION"),
            ("feeRates", "0.990000"),
            ("ruleVersions", "stale-rule"),
        ],
    )
    assert stale_direct.status_code == 200
    assert [row["orderId"] for row in stale_direct.json()["data"]["list"]] == [
        "order-fee-own"
    ]
    stale_direct_export = client.get(
        "/api/v1/order-fee-details/export",
        params=[
            ("feeDirection", "PROMOTION"),
            ("feeRates", "0.990000"),
            ("ruleVersions", "stale-rule"),
        ],
    )
    assert stale_direct_export.status_code == 200
    assert "order-fee-own" in stale_direct_export.content.decode("utf-8-sig")

    management_details = client.get(
        "/api/v1/order-fee-details",
        params={"feeDirection": "MANAGEMENT"},
    )
    assert management_details.status_code == 200
    assert [row["orderId"] for row in management_details.json()["data"]["list"]] == [
        "order-fee-other"
    ]

    management_export = client.get(
        "/api/v1/order-fee-details/export",
        params={"feeDirection": "MANAGEMENT"},
    )
    assert management_export.status_code == 200
    management_export_text = management_export.content.decode("utf-8-sig")
    assert "order-fee-other" in management_export_text
    assert "order-fee-own" not in management_export_text

    other_fee_details = client.get(
        "/api/v1/order-fee-details",
        params={
            "storeId": "store-2",
            "month": "2026-05",
            "feeDirection": "PROMOTION",
        },
    )
    assert other_fee_details.status_code == 403

    locked_details = client.get(
        "/api/v1/order-fee-details",
        params={
            "statementId": "statement-own",
            "statementLineId": "line-own",
            "feeDirection": "PROMOTION",
            "feeRates": "0.100000",
            "ruleVersions": "rule-v1",
        },
    )
    assert locked_details.status_code == 200
    assert locked_details.json()["data"]["context"]["statementStatus"] == "LOCKED"
    locked_row = locked_details.json()["data"]["list"][0]
    assert locked_row["statementEntryId"] == "entry-own"
    assert locked_row["adjustments"] == []
    assert locked_row["adjustedNetFeeCent"] == 100

    stale_context = client.get(
        "/api/v1/order-fee-details",
        params={
            "statementId": "statement-own",
            "statementLineId": "line-own",
            "feeDirection": "PROMOTION",
            "feeRates": "0.200000",
            "ruleVersions": "rule-v1",
        },
    )
    assert stale_context.status_code == 422
    assert stale_context.json()["detail"]["code"] == "VALIDATION_FAILED"


def test_direct_order_fee_details_uses_sql_pagination_and_batched_adjustments(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed_sql: list[str] = []
    original_execute = DashboardDataStore._execute

    def recording_execute(
        self: DashboardDataStore,
        sql: str,
        params: dict | None = None,
    ) -> list[dict]:
        executed_sql.append(sql)
        return original_execute(self, sql, params)

    monkeypatch.setattr(DashboardDataStore, "_execute", recording_execute)
    _login_viewer(client)

    first_page = client.get(
        "/api/v1/order-fee-details",
        params={"feeDirection": "PROMOTION", "pageSize": 1},
    )

    assert first_page.status_code == 200
    assert first_page.json()["data"]["total"] == 2
    assert len(first_page.json()["data"]["list"]) == 1
    assert any(
        "LIMIT :order_fee_limit OFFSET :order_fee_offset" in sql
        for sql in executed_sql
    )

    executed_sql.clear()
    full_page = client.get(
        "/api/v1/order-fee-details",
        params={"feeDirection": "PROMOTION", "pageSize": 50},
    )

    assert full_page.status_code == 200
    adjustment_queries = [
        sql
        for sql in executed_sql
        if "FROM settlement_fee_adjustment" in sql
        and "WHERE original_fee_result_id IN" in sql
    ]
    assert len(adjustment_queries) == 1

    executed_sql.clear()
    adjusted_second_page = client.get(
        "/api/v1/order-fee-details",
        params={
            "feeDirection": "PROMOTION",
            "dataStatus": "ADJUSTED",
            "page": 2,
            "pageSize": 1,
        },
    )

    assert adjusted_second_page.status_code == 200
    assert adjusted_second_page.json()["data"]["total"] == 1
    assert adjusted_second_page.json()["data"]["list"] == []
    assert any(
        "LIMIT :order_fee_limit OFFSET :order_fee_offset" in sql
        and "EXISTS (SELECT 1 FROM settlement_fee_adjustment status_adjustment" in sql
        for sql in executed_sql
    )

    executed_sql.clear()
    locked_page = client.get(
        "/api/v1/order-fee-details",
        params={
            "statementId": "statement-own",
            "statementLineId": "line-own",
            "feeDirection": "PROMOTION",
        },
    )

    assert locked_page.status_code == 200
    assert any(
        "JOIN settlement_statement_entry e" in sql
        and "a.original_fee_result_id IN" in sql
        for sql in executed_sql
    )
    assert not any(
        "WHERE a.original_fee_result_id = :fee_result_id" in sql
        for sql in executed_sql
    )


def test_direct_order_fee_details_respects_empty_store_scope(
    client: TestClient,
) -> None:
    _login_empty_store(client)

    response = client.get(
        "/api/v1/order-fee-details",
        params={"feeDirection": "PROMOTION"},
    )
    export = client.get(
        "/api/v1/order-fee-details/export",
        params={"feeDirection": "PROMOTION"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["list"] == []
    assert response.json()["data"]["total"] == 0
    assert export.status_code == 409
    assert export.json()["detail"]["code"] == "EXPORT_EMPTY"


def test_legacy_viewer_is_mapped_to_global_admin(client: TestClient) -> None:
    _login_viewer(client)

    other_store = client.get("/api/v1/stores/store-2/monthly-settlement?month=2026-05")
    assert other_store.status_code == 200

    details = client.get("/api/v1/order-details?page=1&page_size=50")
    assert details.status_code == 200
    assert {row["order_id"] for row in details.json()["data"]["rows"]} == {
        "order-sale",
        "order-other",
    }

    sales_all_stores = client.get(
        "/api/v1/dashboard/sales?month=2026-05&trend_months=2026-05"
    )
    assert sales_all_stores.status_code == 200
    assert sales_all_stores.json()["data"]["store"] == {
        "store_id": "",
        "store_name": "全部门店",
    }

    admin_accounts = client.get("/api/v1/admin/accounts")
    assert admin_accounts.status_code == 200
    assert all(row["role"] == "store" for row in admin_accounts.json()["data"]["rows"])


def test_unlocked_monthly_statement_reads_current_preview_not_frozen_lines(
    client: TestClient, db_session: Session
) -> None:
    statement = db_session.query(SettlementStatement).filter_by(
        statement_id="statement-own"
    ).one_or_none()
    line = db_session.query(SettlementStatementLine).filter_by(
        statement_line_id="line-own"
    ).one_or_none()
    assert statement is not None and line is not None
    statement.statement_status = 3
    line.original_fee_cent = 999
    line.net_fee_cent = 999
    db_session.commit()
    _login_viewer(client)

    response = client.get(
        "/api/v1/stores/store-1/monthly-settlement?month=2026-05"
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["statement"]["statementStatus"] == "CONFIRMED"
    assert payload["lines"][0]["statementLineId"] is None
    assert payload["lines"][0]["netFeeCent"] == 100


def test_order_fee_context_is_validated_before_detail_filters(
    client: TestClient, db_session: Session
) -> None:
    timestamp = datetime(2026, 5, 2, 8, tzinfo=timezone.utc)
    db_session.add(
        RawDouyinOrder(
            order_id="order-filter-other",
            order_status_normalized="PAID",
            sku_id="sku",
            product_name="Other Product",
            sale_time=timestamp,
            order_paid_amount_cent=1000,
            sale_channel_normalized="LIVE",
        )
    )
    db_session.flush()
    db_session.add_all(
        [
            SettlementFeeResult(
                fee_result_id="fee-filter-other",
                coupon_id="coupon-filter-other",
                order_id="order-filter-other",
                fee_direction=1,
                result_version=1,
                original_business_month="2026-05",
                rule_match_date=date(2026, 5, 2),
                sale_store_id="store-1",
                verify_store_id="store-2",
                sku_id="sku",
                product_scope="all",
                product_type="all",
                sale_channel_normalized="LIVE",
                source_amount_cent=1000,
                refunded_amount_cent=0,
                fee_base_cent=1000,
                fee_rate=Decimal("0.200000"),
                fee_amount_cent=200,
                rule_version="rule-v2",
                scope_rule_version="scope-v1",
                result_status=1,
                calculation_run_id="run-2",
                calculated_at=timestamp,
            ),
            SettlementFeeResultCurrent(
                coupon_id="coupon-filter-other",
                fee_direction=1,
                fee_result_id="fee-filter-other",
            ),
        ]
    )
    db_session.commit()
    _login_viewer(client)

    response = client.get(
        "/api/v1/order-fee-details",
        params=[
            ("storeId", "store-1"),
            ("month", "2026-05"),
            ("feeDirection", "PROMOTION"),
            ("feeRates", "0.100000"),
            ("feeRates", "0.200000"),
            ("ruleVersions", "rule-v1"),
            ("ruleVersions", "rule-v2"),
            ("q", "order-fee-own"),
        ],
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["context"]["feeRates"] == ["0.100000", "0.200000"]
    assert [row["orderId"] for row in payload["list"]] == ["order-fee-own"]


def test_monthly_settlement_requires_store_specific_month_context(
    client: TestClient,
) -> None:
    _login_viewer(client)

    response = client.get(
        "/api/v1/stores/store-3/monthly-settlement?month=2026-05"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"


def test_adjustment_only_preview_line_keeps_original_rate_context(
    client: TestClient, db_session: Session
) -> None:
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-06",
            product_type="all",
            store_id="store-1",
            estimated_receivable_commission_cent=-10,
            commissionable_total_cent=-100,
            estimated_payable_commission_cent=0,
            updated_at=datetime(2026, 6, 1, 8, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    _login_viewer(client)

    response = client.get(
        "/api/v1/stores/store-1/monthly-settlement?month=2026-06"
    )

    assert response.status_code == 200
    line = response.json()["data"]["lines"][0]
    assert line["originalEntryCount"] == 0
    assert line["adjustmentEntryCount"] == 1
    assert line["feeRates"] == ["0.100000"]
    assert line["ruleVersions"] == ["rule-v1"]


def test_preview_rate_context_ignores_superseded_fee_results(
    client: TestClient, db_session: Session
) -> None:
    statement = db_session.query(SettlementStatement).filter_by(
        statement_id="statement-own"
    ).one()
    statement.statement_status = 3
    current_result = db_session.query(SettlementFeeResult).filter_by(
        fee_result_id="fee-own"
    ).one()
    current_result.result_version = 2
    db_session.flush()
    db_session.add(
        SettlementFeeResult(
            fee_result_id="fee-own-superseded",
            coupon_id="coupon-fee-own",
            order_id="order-fee-own",
            fee_direction=1,
            result_version=1,
            original_business_month="2026-05",
            rule_match_date=date(2026, 5, 1),
            sale_store_id="store-1",
            verify_store_id="store-2",
            sku_id="sku",
            product_scope="all",
            product_type="all",
            sale_channel_normalized="LIVE",
            source_amount_cent=1000,
            refunded_amount_cent=0,
            fee_base_cent=1000,
            fee_rate=Decimal("0.050000"),
            fee_amount_cent=50,
            rule_version="rule-old",
            scope_rule_version="scope-v1",
            result_status=2,
            calculation_run_id="run-old",
            calculated_at=datetime(2026, 5, 1, 7, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    _login_viewer(client)

    response = client.get(
        "/api/v1/stores/store-1/monthly-settlement?month=2026-05"
    )

    assert response.status_code == 200
    line = response.json()["data"]["lines"][0]
    assert line["feeRates"] == ["0.100000"]
    assert line["ruleVersions"] == ["rule-v1"]


def test_statement_detail_context_requires_locked_statement(
    client: TestClient, db_session: Session
) -> None:
    statement = db_session.query(SettlementStatement).filter_by(
        statement_id="statement-own"
    ).one()
    statement.statement_status = 3
    db_session.commit()
    _login_viewer(client)

    response = client.get(
        "/api/v1/order-fee-details",
        params={
            "statementId": "statement-own",
            "statementLineId": "line-own",
            "feeDirection": "PROMOTION",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_FAILED"


def test_unauthorized_statement_scope_is_hidden_before_status_validation(
    client: TestClient, db_session: Session
) -> None:
    statement = db_session.query(SettlementStatement).filter_by(
        statement_id="statement-own"
    ).one()
    statement.store_id = "store-2"
    statement.statement_status = 3
    db_session.commit()
    _login_store(client)

    response = client.get(
        "/api/v1/order-fee-details",
        params={
            "statementId": "statement-own",
            "statementLineId": "line-own",
            "feeDirection": "PROMOTION",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "DATA_SCOPE_FORBIDDEN"
