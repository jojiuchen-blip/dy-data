from __future__ import annotations

import sys
import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import DashboardDataStore, get_data_store, sanitize_error_message  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    AggStoreMonthlySettlement,
    AggStoreRanking,
    DimSkuProductRule,
    DimStore,
    SettlementOrderDetail,
)


def deferred_field(*parts: str) -> str:
    return "_".join(parts)


class FakeStore:
    def list_stores(self, scope_store_ids=None):
        return [{"store_id": "store_001", "store_name": "Store One"}]

    def list_product_types(self):
        return ["all", "basic_service"]

    def list_product_scopes(self):
        return ["all", "精诚养车"]

    def product_scope_type_map(self):
        return {"精诚养车": ["basic_service"]}

    def list_sale_months(self):
        return ["2026-05"]

    def list_verify_months(self):
        return ["2026-05"]

    def list_statement_months(self):
        return ["2026-08", "2026-07"]

    def store_exists(self, store_id: str):
        return store_id == "store_001"

    def monthly_settlement_context_exists(self, store_id: str, month: str):
        return store_id == "store_001" and month in {"2026-08", "2026-07", "2026-05"}

    def store_ranking_report(self, filters: dict):
        return {
            "period_type": filters["period_type"],
            "period_key": filters["period_key"],
            "product_scope": filters["product_scope"],
            "product_type": filters["product_type"],
            "formal_period_start_month": "2026-08",
            "scope_mode": filters["scope_mode"],
            "totals": {
                "sales_order_count": 30,
                "sales_amount_cent": 300000,
                "verified_order_count": 20,
                "verified_amount_cent": 200000,
                "promotion_net_fee_cent": 4200,
                "management_net_fee_cent": 1200,
                "net_settlement_reference_cent": 3000,
            },
            "list": [
                {
                    "rank": 1,
                    "store_id": "store_001",
                    "store_name": "Store One",
                    "sales_order_count": 3,
                    "sales_amount_cent": 30000,
                    "verified_order_count": 2,
                    "verified_amount_cent": 20000,
                    "promotion_net_fee_cent": 420,
                    "management_net_fee_cent": 120,
                    "net_settlement_reference_cent": 300,
                }
            ],
            "total": 1,
            "page": filters["page"],
            "page_size": filters["page_size"],
        }

    def monthly_settlement_report(self, filters: dict):
        return {
            "store": {"store_id": filters["store_id"], "store_name": "Store One"},
            "month": filters["month"],
            "product_scope": filters["product_scope"],
            "product_type": filters["product_type"],
            "is_formal_period": filters["month"] >= "2026-08",
            "statement": None,
            "metrics": {
                "sales_order_count": 3,
                "sales_amount_cent": 30000,
                "verified_order_count": 2,
                "verified_amount_cent": 20000,
                "promotion_base_cent": 21000,
                "promotion_original_fee_cent": 1680,
                "promotion_adjustment_fee_cent": -80,
                "promotion_net_fee_cent": 1600,
                "management_base_cent": 10000,
                "management_original_fee_cent": 1000,
                "management_adjustment_fee_cent": -100,
                "management_net_fee_cent": 900,
                "net_settlement_reference_cent": 700,
            },
            "lines": [
                {
                    "statement_line_id": None,
                    "fee_direction": "PROMOTION",
                    "product_scope": "精诚养车",
                    "product_type": "basic_service",
                    "original_entry_count": 1,
                    "adjustment_entry_count": 1,
                    "original_base_cent": 22000,
                    "adjustment_base_cent": -1000,
                    "net_base_cent": 21000,
                    "original_fee_cent": 1680,
                    "adjustment_fee_cent": -80,
                    "net_fee_cent": 1600,
                    "min_fee_rate": "0.080000",
                    "max_fee_rate": "0.080000",
                    "rule_version_count": 1,
                    "fee_rates": ["0.080000"],
                    "rule_versions": ["rule-v1"],
                }
            ],
        }

    def order_fee_details(self, filters: dict):
        return {
            "context": {
                "statement_id": filters.get("statement_id"),
                "statement_line_id": filters.get("statement_line_id"),
                "store_id": filters.get("store_id"),
                "month": filters.get("month"),
                "fee_direction": filters["fee_direction"],
                "product_scope": filters["product_scope"],
                "product_type": filters["product_type"],
                "fee_rates": filters.get("fee_rates", []),
                "rule_versions": filters.get("rule_versions", []),
                "statement_status": None,
            },
            "list": [
                {
                    "fee_result_id": "fee-1",
                    "statement_entry_id": None,
                    "order_id": "order_001",
                    "coupon_id": "coupon_001",
                    "order_status": "PAID",
                    "coupon_status": "VERIFIED",
                    "fee_direction": filters["fee_direction"],
                    "original_business_month": "2026-08",
                    "sale_month": "2026-08",
                    "verify_month": "2026-08",
                    "rule_match_date": "2026-08-02",
                    "sale_time": "2026-08-02T08:00:00+08:00",
                    "verify_time": "2026-08-03T08:00:00+08:00",
                    "sale_store_id": "store_001",
                    "sale_store_name": "Store One",
                    "verify_store_id": "store_001",
                    "verify_store_name": "Store One",
                    "sku_id": "sku_001",
                    "sku_name": "基础养护 SKU",
                    "product_name": "基础养护",
                    "product_scope": "精诚养车",
                    "product_type": "basic_service",
                    "sale_channel": "LIVE",
                    "source_amount_cent": 10000,
                    "refunded_amount_cent": 1000,
                    "original_base_cent": 10000,
                    "fee_rate": "0.080000",
                    "original_fee_cent": 800,
                    "adjustment_base_cent": -1000,
                    "adjustment_fee_cent": -80,
                    "adjusted_net_base_cent": 9000,
                    "adjusted_net_fee_cent": 720,
                    "rule_version": "rule-v1",
                    "result_status": "VALID",
                    "statement_id": None,
                    "statement_line_id": None,
                    "adjustments": [],
                }
            ],
            "total": 1,
            "page": filters["page"],
            "page_size": filters["page_size"],
        }

    def order_fee_details_export_csv(self, filters: dict):
        if filters.get("q") == "missing":
            return ""
        return "订单ID,券ID,费用方向,规则版本\r\norder_001,coupon_001,PROMOTION,rule-v1\r\n"

    def latest_job(self):
        return {
            "job_id": "job_001",
            "job_name": "settlement",
            "status": "success",
            "started_at": datetime(2026, 5, 2, tzinfo=timezone.utc),
            "finished_at": datetime(2026, 5, 2, 1, tzinfo=timezone.utc),
            "success_count": 8,
            "failed_count": 0,
            "error_message": None,
        }

    def recent_jobs(self, limit: int):
        return [self.latest_job()][:limit]

    def store_ranking(
        self, *, month: str, product_type: str, limit: int, product_scope: str = "all"
    ):
        return [
            {
                "rank": 1,
                "store_id": "store_001",
                "store_name": "Store One",
                "sales_order_count": 3,
                "self_sold_self_verified_count": 1,
                "self_sold_other_verified_count": 2,
                "other_sold_self_verified_count": 0,
                "self_verify_income_cent": 10000,
                "effective_commission_income_cent": 1680,
            }
        ][:limit]

    def store_ranking_totals(
        self, *, month: str, product_type: str, product_scope: str = "all"
    ):
        return {
            "sales_order_count": 30,
            "self_verify_income_cent": 25000,
            "effective_commission_income_cent": 4200,
        }

    def monthly_settlement(
        self,
        *,
        store_id: str,
        month: str,
        product_type: str,
        product_scope: str = "all",
    ):
        return {
            "store": {"store_id": store_id, "store_name": "Store One"},
            "month": month,
            "product_scope": product_scope,
            "product_type": product_type,
            "metrics": {
                "estimated_receivable_commission_cent": 1680,
                "commissionable_total_cent": 16800,
                "estimated_payable_commission_cent": 2680,
            },
            "tables": {
                "receivable_commissions": [
                    {
                        "product_type": "basic_service",
                        "verified_coupon_count": 1,
                        "paid_amount_cent": 16800,
                        "commission_rate": 0.1,
                        "commissionable_total_cent": 16800,
                        "estimated_receivable_commission_cent": 1680,
                    }
                ],
                "payable_commissions": [
                    {
                        "product_type": "basic_service",
                        "verified_coupon_count": 1,
                        "paid_amount_cent": 26800,
                        "commission_rate": 0.1,
                        "payable_commission_cent": 2680,
                    }
                ],
                "non_commission_orders": [],
            },
        }

    def sales_dashboard(
        self,
        *,
        store_id: str | None,
        month: str,
        product_type: str,
        trend_months: list[str],
        product_scope: str = "all",
    ):
        store = (
            {"store_id": "", "store_name": "全部门店"}
            if store_id is None
            else {"store_id": store_id, "store_name": "Store One"}
        )
        return {
            "store": store,
            "month": month,
            "product_scope": product_scope,
            "product_type": product_type,
            "metrics": {
                "total_sales_order_count": 2,
                "self_verify_order_count": 1,
                "self_verify_rate": 0.5,
                "total_verify_order_count": 1,
                "actual_verify_amount_cent": 16800,
                "avg_verify_cycle_days": 3,
            },
            "product_rows": [
                {
                    "product_type": "basic_service",
                    "total_sales_order_count": 2,
                    "self_verify_order_count": 1,
                    "self_verify_rate": 0.5,
                    "total_verify_order_count": 1,
                    "actual_verify_amount_cent": 16800,
                    "avg_verify_cycle_days": 3,
                }
            ],
            "trend_rows": [
                {
                    "month": item,
                    "order_count": 2,
                    "verify_order_count": 1,
                }
                for item in trend_months
            ],
            "cycle_rows": [
                {
                    "product_type": "basic_service",
                    "count": 1,
                    "min_days": 3,
                    "q1_days": 3,
                    "median_days": 3,
                    "q3_days": 3,
                    "max_days": 3,
                    "avg_days": 3,
                    "sample_points": [
                        {
                            "order_id": "order_001",
                            "cycle_days": 3,
                            "sale_time": datetime(2026, 5, 1, 8, tzinfo=timezone.utc),
                            "verify_time": datetime(2026, 5, 4, 8, tzinfo=timezone.utc),
                        }
                    ],
                }
            ],
            "source_row_count": 1,
        }

    def order_details(self, filters: dict):
        return {
            "rows": [
                {
                    "order_id": "order_001",
                    "coupon_id": "coupon_001",
                    "sku_id": "sku_001",
                    "owner_account_id": "acct_001",
                    "owner_account_name": "Owner",
                    "product_type": "basic_service",
                    "sale_store_id": "store_001",
                    "sale_store_name": "Store One",
                    "sale_store_subject_name": "Subject One",
                    "sale_time": datetime(2026, 5, 1, 8, tzinfo=timezone.utc),
                    "is_verified": True,
                    "verify_store_id": "store_002",
                    "verify_store_name": "Store Two",
                    "verify_store_subject_name": "Subject Two",
                    "verify_time": datetime(2026, 5, 4, 8, tzinfo=timezone.utc),
                    "relation_type": "cross_store",
                    "is_commissionable": True,
                    "is_refund_excluded": False,
                    "paid_amount_cent": 16800,
                    "commission_rate": 0.1,
                    "receivable_commission_cent": 1680,
                    "payable_commission_cent": 0,
                }
            ],
            "pagination": {
                "page": filters["page"],
                "page_size": filters["page_size"],
                "total": 1,
                "total_pages": 1,
            },
        }

    def order_details_export_csv(self, filters: dict):
        return (
            "order_id,coupon_id,sku_id,owner_account_id,owner_account_name,"
            "product_type,sale_store_id,sale_store_name,sale_store_subject_name,"
            "sale_time,is_verified,verify_store_id,verify_store_name,"
            "verify_store_subject_name,verify_time,relation_type,"
            "is_commissionable,is_refund_excluded,paid_amount_cent,commission_rate,"
            "receivable_commission_cent,payable_commission_cent\r\n"
            "order_001,coupon_001,sku_001,acct_001,Owner,basic_service,"
            "store_001,Store One,Subject One,2026-05-01T08:00:00+00:00,True,store_002,"
            "Store Two,Subject Two,2026-05-04T08:00:00+00:00,cross_store,True,False,16800,"
            "0.1,1680,0\r\n"
        )

    def export_filter_header(self, filters: dict):
        return '{"sale_store_id":"store_001"}'


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    app = create_app()
    app.dependency_overrides[get_data_store] = lambda: FakeStore()
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert response.status_code == 200


def test_filter_metadata_contract(client: TestClient):
    _login(client)
    response = client.get("/api/v1/meta/filters")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["stores"] == [{"storeId": "store_001", "storeName": "Store One"}]
    assert data["productScopes"] == ["all", "精诚养车"]
    assert data["productScopeTypeMap"] == {"精诚养车": ["basic_service"]}
    assert data["productTypes"] == ["all", "basic_service"]
    assert "latest_job" not in data


def test_settlement_reporting_target_contracts_are_camel_case(client: TestClient):
    _login(client)

    metadata = client.get("/api/v1/meta/filters")
    assert metadata.status_code == 200
    metadata_payload = metadata.json()
    assert metadata_payload["data"]["stores"] == [
        {"storeId": "store_001", "storeName": "Store One"}
    ]
    assert metadata_payload["data"]["statementMonths"] == ["2026-08", "2026-07"]
    assert metadata_payload["data"]["feeDirections"] == ["PROMOTION", "MANAGEMENT"]
    assert metadata_payload["data"]["formalPeriodStartMonth"] == "2026-08"
    assert metadata_payload["meta"]["requestId"].startswith("req_")

    ranking = client.get(
        "/api/v1/dashboard/store-ranking",
        params={
            "periodType": "MONTHLY",
            "periodKey": "2026-08",
            "productScope": "all",
            "productType": "all",
            "sortBy": "NET_SETTLEMENT_REFERENCE",
            "sortOrder": "DESC",
            "page": 1,
            "pageSize": 20,
        },
    )
    assert ranking.status_code == 200
    ranking_data = ranking.json()["data"]
    assert ranking_data["totals"]["promotionNetFeeCent"] == 4200
    assert ranking_data["list"][0]["storeId"] == "store_001"
    assert ranking_data["pageSize"] == 20
    assert "rows" not in ranking_data

    settlement = client.get(
        "/api/v1/stores/store_001/monthly-settlement",
        params={"month": "2026-08", "productScope": "all", "productType": "all"},
    )
    assert settlement.status_code == 200
    settlement_data = settlement.json()["data"]
    assert settlement_data["isFormalPeriod"] is True
    assert settlement_data["metrics"]["promotionNetFeeCent"] == 1600
    assert settlement_data["lines"][0]["feeRates"] == ["0.080000"]
    assert "tables" not in settlement_data

    details = client.get(
        "/api/v1/order-fee-details",
        params={
            "storeId": "store_001",
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "feeRates": "0.080000",
            "ruleVersions": "rule-v1",
            "page": 1,
            "pageSize": 50,
        },
    )
    assert details.status_code == 200
    detail_data = details.json()["data"]
    assert detail_data["context"]["feeRates"] == ["0.080000"]
    assert detail_data["list"][0]["adjustedNetFeeCent"] == 720
    assert "id" not in detail_data["list"][0]
    assert "rawOrderId" not in detail_data["list"][0]

    export = client.get(
        "/api/v1/order-fee-details/export",
        params={
            "storeId": "store_001",
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "page": 9,
            "pageSize": 1,
        },
    )
    assert export.status_code == 200
    assert export.content.startswith(b"\xef\xbb\xbf")
    assert "text/csv" in export.headers["content-type"]
    assert export.headers["x-request-id"].startswith("req_")
    assert "order_001" in export.content.decode("utf-8-sig")


def test_settlement_reporting_validation_is_structured(client: TestClient):
    _login(client)

    response = client.get(
        "/api/v1/order-fee-details",
        params={"storeId": "store_001", "feeDirection": "PROMOTION"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_FAILED"
    assert response.json()["detail"]["requestId"].startswith("req_")


def test_order_fee_export_empty_result_is_a_structured_conflict(
    client: TestClient,
):
    _login(client)

    response = client.get(
        "/api/v1/order-fee-details/export",
        params={
            "storeId": "store_001",
            "month": "2026-08",
            "feeDirection": "PROMOTION",
            "q": "missing",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EXPORT_EMPTY"
    assert response.json()["detail"]["requestId"].startswith("req_")


def test_monthly_settlement_missing_store_is_structured_not_found(
    client: TestClient,
):
    _login(client)

    response = client.get(
        "/api/v1/stores/missing/monthly-settlement",
        params={"month": "2026-08"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"


def test_order_fee_detail_source_contexts_are_mutually_exclusive(
    client: TestClient,
):
    _login(client)

    orphan_line = client.get(
        "/api/v1/order-fee-details",
        params={
            "statementLineId": "line-1",
            "storeId": "store_001",
            "month": "2026-08",
            "feeDirection": "PROMOTION",
        },
    )
    mixed_context = client.get(
        "/api/v1/order-fee-details",
        params={
            "statementId": "statement-1",
            "statementLineId": "line-1",
            "storeId": "store_001",
            "month": "2026-08",
            "feeDirection": "PROMOTION",
        },
    )

    assert orphan_line.status_code == 422
    assert orphan_line.json()["detail"]["errors"][0]["field"] == "statementLineId"
    assert mixed_context.status_code == 422
    assert mixed_context.json()["detail"]["errors"][0]["field"] == "storeId"


def test_dashboard_contract_responses_do_not_expose_deferred_fields(
    client: TestClient,
):
    _login(client)
    ranking = client.get(
        "/api/v1/dashboard/store-ranking?periodType=MONTHLY&periodKey=2026-05"
    )
    settlement = client.get(
        "/api/v1/stores/store_001/monthly-settlement?month=2026-05"
    )
    sales = client.get(
        "/api/v1/dashboard/sales?store_id=store_001&month=all&trend_months=2026-05"
    )
    details = client.get("/api/v1/order-details?page=1&page_size=50")

    assert ranking.status_code == 200
    ranking_payload = ranking.json()
    assert ranking_payload["data"]["list"][0]["salesOrderCount"] == 3
    assert ranking_payload["data"]["totals"]["salesOrderCount"] == 30
    ranking_definitions = {
        definition["key"]: definition for definition in ranking_payload["definitions"]
    }
    assert ranking_definitions["salesOrderCount"]["label"] == "销售订单数量"
    assert "完整筛选集合" in ranking_definitions["salesOrderCount"]["description"]
    assert ranking_definitions["promotionNetFeeCent"]["label"] == "推广服务费净额"

    assert settlement.status_code == 200
    settlement_payload = settlement.json()
    settlement_definitions = {
        definition["key"]: definition for definition in settlement_payload["definitions"]
    }
    assert (
        settlement_definitions["promotionNetFeeCent"]["label"]
        == "应收推广服务费净额"
    )
    assert "commissionableTotalCent" not in settlement_definitions
    assert (
        "调整后净额"
        in settlement_definitions["managementNetFeeCent"]["description"]
    )
    assert (
        settlement_payload["data"]["metrics"]["promotionNetFeeCent"] == 1600
    )
    settlement_text = settlement.text
    assert deferred_field("current", "receivable", "commission", "cent") not in settlement_text
    assert deferred_field("invoiced", "coupon", "count") not in settlement_text
    assert deferred_field("pending", "invoice", "commission", "cent") not in settlement_text

    assert sales.status_code == 200
    sales_payload = sales.json()
    sales_definitions = {
        definition["key"]: definition for definition in sales_payload["definitions"]
    }
    assert sales_payload["data"]["trend_rows"] == [
        {"month": "2026-05", "order_count": 2, "verify_order_count": 1}
    ]
    assert sales_payload["data"]["product_scope"] == "all"
    assert sales_definitions["total_verify_order_count"]["label"] == "实际核销总数"
    sales_order_description = sales_definitions["total_sales_order_count"]["description"]
    assert "退款订单不计入" in sales_order_description
    assert "is_refund_excluded=true" not in sales_order_description
    assert deferred_field("refund", "amount", "cent") not in sales.text

    assert details.status_code == 200
    detail_row = details.json()["data"]["rows"][0]
    assert detail_row["coupon_id"] == "coupon_001"
    assert "id" not in detail_row
    assert "raw_order_id" not in detail_row
    assert detail_row["sale_store_subject_name"] == "Subject One"
    assert detail_row["verify_store_subject_name"] == "Subject Two"
    assert detail_row["is_refund_excluded"] is False
    assert deferred_field("invoice", "status") not in detail_row
    assert deferred_field("refund", "status") not in detail_row
    assert deferred_field("refund", "amount", "cent") not in detail_row


def test_sales_dashboard_all_stores_default_for_global_account(client: TestClient):
    _login(client)

    response = client.get(
        "/api/v1/dashboard/sales?month=all&trend_months=2026-05"
    )

    assert response.status_code == 200
    assert response.json()["data"]["store"] == {
        "store_id": "",
        "store_name": "全部门店",
    }


def test_order_details_export_is_csv_and_omits_deferred_fields(client: TestClient):
    _login(client)
    response = client.get("/api/v1/order-details/export?sale_store_id=store_001")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["x-export-filters"] == '{"sale_store_id":"store_001"}'
    assert "attachment;" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "order_id,coupon_id" in response.text
    assert "is_refund_excluded" in response.text
    export_header = next(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))
    assert "id" not in export_header
    assert "raw_order_id" not in export_header
    assert deferred_field("invoice", "status") not in response.text
    assert deferred_field("refund", "amount", "cent") not in response.text


def test_recent_jobs_contract(client: TestClient):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert login.status_code == 200

    response = client.get("/api/v1/jobs/recent?limit=5")

    assert response.status_code == 200
    assert response.json()["data"]["rows"][0]["status"] == "success"


def test_store_ranking_totals_include_all_matching_rows(db_session: Session):
    timestamp = datetime(2026, 5, 1, 8, tzinfo=timezone.utc)
    db_session.add_all(
        [
            AggStoreRanking(
                month="2026-05",
                product_type="all",
                store_id="store_001",
                store_name="Store One",
                sales_order_count=10,
                self_verify_income_cent=10000,
                effective_commission_income_cent=1000,
                updated_at=timestamp,
            ),
            AggStoreRanking(
                month="2026-05",
                product_type="all",
                store_id="store_002",
                store_name="Store Two",
                sales_order_count=7,
                self_verify_income_cent=20000,
                effective_commission_income_cent=2000,
                updated_at=timestamp,
            ),
            AggStoreRanking(
                month="2026-05",
                product_type="service",
                store_id="store_003",
                store_name="Store Three",
                sales_order_count=99,
                self_verify_income_cent=99000,
                effective_commission_income_cent=9900,
                updated_at=timestamp,
            ),
        ]
    )
    db_session.commit()

    store = DashboardDataStore(db_session)
    rows = store.store_ranking(month="2026-05", product_type="all", limit=1)
    totals = store.store_ranking_totals(month="2026-05", product_type="all")

    assert len(rows) == 1
    assert rows[0]["store_id"] == "store_001"
    assert totals == {
        "sales_order_count": 17,
        "self_verify_income_cent": 30000,
        "effective_commission_income_cent": 3000,
    }


def test_target_store_ranking_totals_and_rank_are_stable_across_pages(
    db_session: Session,
):
    timestamp = datetime(2026, 8, 1, 8, tzinfo=timezone.utc)
    db_session.add_all(
        [
            AggStoreRanking(
                period_type=1,
                period_key="2026-08",
                month="2026-08",
                store_id="store-a",
                store_name="Store A",
                product_scope="all",
                product_type="all",
                sales_order_count=2,
                sales_amount_cent=20000,
                verified_order_count=1,
                verified_amount_cent=10000,
                promotion_net_fee_cent=1600,
                management_net_fee_cent=300,
                net_settlement_reference_cent=1300,
                projection_run_id="run-ranking",
                updated_at=timestamp,
            ),
            AggStoreRanking(
                period_type=1,
                period_key="2026-08",
                month="2026-08",
                store_id="store-b",
                store_name="Store B",
                product_scope="all",
                product_type="all",
                sales_order_count=3,
                sales_amount_cent=30000,
                verified_order_count=2,
                verified_amount_cent=20000,
                promotion_net_fee_cent=2400,
                management_net_fee_cent=500,
                net_settlement_reference_cent=1900,
                projection_run_id="run-ranking",
                updated_at=timestamp,
            ),
        ]
    )
    db_session.commit()
    store = DashboardDataStore(db_session)
    base_filters = {
        "period_type": "MONTHLY",
        "period_key": "2026-08",
        "product_scope": "all",
        "product_type": "all",
        "q": None,
        "sort_by": "SALES_AMOUNT",
        "sort_order": "DESC",
        "page_size": 1,
        "scope_mode": "AUTHORIZED",
        "scope_store_ids": None,
    }

    first_page = store.store_ranking_report({**base_filters, "page": 1})
    second_page = store.store_ranking_report({**base_filters, "page": 2})

    assert first_page["list"][0]["store_id"] == "store-b"
    assert first_page["list"][0]["rank"] == 1
    assert second_page["list"][0]["store_id"] == "store-a"
    assert second_page["list"][0]["rank"] == 2
    assert first_page["totals"] == second_page["totals"]
    assert first_page["totals"]["sales_amount_cent"] == 50000
    assert first_page["total"] == 2

    early_cumulative = store.store_ranking_report(
        {
            **base_filters,
            "period_type": "CUMULATIVE",
            "period_key": "2026-07",
            "page": 1,
        }
    )
    assert early_cumulative["list"] == []
    assert early_cumulative["totals"]["sales_amount_cent"] == 0


def test_product_scope_filters_ranking_settlement_and_details(db_session: Session):
    timestamp = datetime(2026, 5, 1, 8, tzinfo=timezone.utc)
    verify_time = datetime(2026, 5, 4, 8, tzinfo=timezone.utc)
    db_session.add_all(
        [
            DimStore(
                store_id="store_scope",
                store_name="Scope Store",
                certified_subject_name="Scope Subject",
            ),
            DimStore(
                store_id="store_other",
                store_name="Other Store",
                certified_subject_name="Other Subject",
            ),
            DimSkuProductRule(
                sku_id="sku_scope",
                product_scope="精诚养车",
                product_type="268保养",
                commission_rate=Decimal("0.1000"),
                is_service_product=True,
            ),
            AggStoreRanking(
                month="2026-05",
                product_type="268保养",
                store_id="store_scope",
                store_name="Scope Store",
                sales_order_count=3,
                self_verify_income_cent=3000,
                effective_commission_income_cent=300,
                updated_at=timestamp,
            ),
            AggStoreRanking(
                month="2026-05",
                product_type="Other Service",
                store_id="store_scope",
                store_name="Scope Store",
                sales_order_count=9,
                self_verify_income_cent=9000,
                effective_commission_income_cent=900,
                updated_at=timestamp,
            ),
            AggStoreMonthlySettlement(
                month="2026-05",
                store_id="store_scope",
                product_type="268保养",
                estimated_receivable_commission_cent=300,
                commissionable_total_cent=3000,
                estimated_payable_commission_cent=30,
                updated_at=timestamp,
            ),
            AggStoreMonthlySettlement(
                month="2026-05",
                store_id="store_scope",
                product_type="Other Service",
                estimated_receivable_commission_cent=900,
                commissionable_total_cent=9000,
                estimated_payable_commission_cent=90,
                updated_at=timestamp,
            ),
        ]
    )
    for coupon_id, product_type, amount in [
        ("coupon_scope", "268保养", 3000),
        ("coupon_other", "Other Service", 9000),
    ]:
        db_session.add(
            SettlementOrderDetail(
                coupon_id=coupon_id,
                order_id=coupon_id.replace("coupon", "order"),
                sku_id="sku_001",
                owner_account_id="acct_001",
                owner_account_name="Owner",
                product_type=product_type,
                sale_store_id="store_scope",
                sale_store_name="Scope Store",
                sale_time=timestamp,
                is_verified=True,
                verify_store_id="store_other",
                verify_store_name="Other Store",
                verify_time=verify_time,
                relation_type="cross_store",
                is_commissionable=True,
                is_refund_excluded=False,
                paid_amount_cent=amount,
                commission_rate=Decimal("0.1000"),
                receivable_commission_cent=amount // 10,
                payable_commission_cent=0,
                source_run_id="test-run",
                updated_at=timestamp,
            )
        )
    db_session.commit()

    store = DashboardDataStore(db_session)
    ranking_rows = store.store_ranking(
        month="2026-05",
        product_scope="精诚养车",
        product_type="all",
        limit=10,
    )
    ranking_totals = store.store_ranking_totals(
        month="2026-05",
        product_scope="精诚养车",
        product_type="all",
    )
    settlement = store.monthly_settlement(
        store_id="store_scope",
        month="2026-05",
        product_scope="精诚养车",
        product_type="all",
    )
    details = store.order_details(
        {
            "product_scope": "精诚养车",
            "product_type": "all",
            "page": 1,
            "page_size": 50,
        }
    )

    assert [row["store_id"] for row in ranking_rows] == ["store_scope"]
    assert ranking_rows[0]["sales_order_count"] == 3
    assert ranking_totals["sales_order_count"] == 3
    assert settlement["product_scope"] == "精诚养车"
    assert settlement["metrics"]["commissionable_total_cent"] == 3000
    assert [
        row["product_type"]
        for row in settlement["tables"]["receivable_commissions"]
    ] == ["268保养"]
    assert [row["coupon_id"] for row in details["rows"]] == ["coupon_scope"]


def test_sales_dashboard_trend_counts_actual_verify_store_orders(db_session: Session):
    sale_time = datetime(2026, 5, 1, 8, tzinfo=timezone.utc)
    verify_time = datetime(2026, 5, 4, 8, tzinfo=timezone.utc)
    db_session.add_all(
        [
            DimStore(store_id="store_a", store_name="Store A", certified_subject_name="Subject A"),
            DimStore(store_id="store_b", store_name="Store B", certified_subject_name="Subject B"),
        ]
    )

    rows = [
        ("coupon_self", "order_self", "store_a", "Store A", "store_a", "Store A", 10000),
        ("coupon_cross_out", "order_cross_out", "store_a", "Store A", "store_b", "Store B", 20000),
        ("coupon_cross_in", "order_cross_in", "store_b", "Store B", "store_a", "Store A", 30000),
    ]
    for coupon_id, order_id, sale_store_id, sale_store_name, verify_store_id, verify_store_name, amount in rows:
        db_session.add(
            SettlementOrderDetail(
                coupon_id=coupon_id,
                order_id=order_id,
                sku_id="sku_001",
                owner_account_id="acct_001",
                owner_account_name="Owner",
                product_type="basic_service",
                sale_store_id=sale_store_id,
                sale_store_name=sale_store_name,
                sale_time=sale_time,
                is_verified=True,
                verify_store_id=verify_store_id,
                verify_store_name=verify_store_name,
                verify_time=verify_time,
                relation_type="same_store" if sale_store_id == verify_store_id else "cross_store",
                is_commissionable=True,
                is_refund_excluded=False,
                paid_amount_cent=amount,
                commission_rate=Decimal("0.1000"),
                receivable_commission_cent=0,
                payable_commission_cent=0,
                source_run_id="test-run",
                updated_at=sale_time,
            )
        )
    db_session.commit()

    dashboard = DashboardDataStore(db_session).sales_dashboard(
        store_id="store_a",
        month="all",
        product_type="all",
        trend_months=["2026-05"],
    )

    assert dashboard["metrics"]["total_sales_order_count"] == 2
    assert dashboard["metrics"]["self_verify_order_count"] == 1
    assert dashboard["metrics"]["total_verify_order_count"] == 2
    assert dashboard["metrics"]["actual_verify_amount_cent"] == 40000
    assert dashboard["trend_rows"] == [
        {"month": "2026-05", "order_count": 2, "verify_order_count": 2}
    ]

    all_store_dashboard = DashboardDataStore(db_session).sales_dashboard(
        store_id=None,
        month="all",
        product_type="all",
        trend_months=["2026-05"],
    )

    assert all_store_dashboard["store"] == {
        "store_id": "",
        "store_name": "全部门店",
    }
    assert all_store_dashboard["metrics"]["total_sales_order_count"] == 3
    assert all_store_dashboard["metrics"]["self_verify_order_count"] == 1
    assert all_store_dashboard["metrics"]["total_verify_order_count"] == 3
    assert all_store_dashboard["metrics"]["actual_verify_amount_cent"] == 60000
    assert all_store_dashboard["trend_rows"] == [
        {"month": "2026-05", "order_count": 3, "verify_order_count": 3}
    ]


def test_sales_dashboard_product_scope_filters_mapped_product_types(
    db_session: Session,
):
    sale_time = datetime(2026, 5, 1, 8, tzinfo=timezone.utc)
    verify_time = datetime(2026, 5, 4, 8, tzinfo=timezone.utc)
    db_session.add(
        DimStore(
            store_id="store_scope",
            store_name="Scope Store",
            certified_subject_name="Scope Subject",
        )
    )
    db_session.add(
        DimSkuProductRule(
            sku_id="sku_scope",
            product_scope="精诚养车",
            product_type="268保养",
            commission_rate=Decimal("0.1000"),
            is_service_product=True,
        )
    )
    for coupon_id, order_id, product_type, amount in [
        ("coupon_scope", "order_scope", "268保养", 10000),
        ("coupon_other", "order_other", "Other Service", 20000),
    ]:
        db_session.add(
            SettlementOrderDetail(
                coupon_id=coupon_id,
                order_id=order_id,
                sku_id="sku_001",
                owner_account_id="acct_001",
                owner_account_name="Owner",
                product_type=product_type,
                sale_store_id="store_scope",
                sale_store_name="Scope Store",
                sale_time=sale_time,
                is_verified=True,
                verify_store_id="store_scope",
                verify_store_name="Scope Store",
                verify_time=verify_time,
                relation_type="same_store",
                is_commissionable=True,
                is_refund_excluded=False,
                paid_amount_cent=amount,
                commission_rate=Decimal("0.1000"),
                receivable_commission_cent=0,
                payable_commission_cent=0,
                source_run_id="test-run",
                updated_at=sale_time,
            )
        )
    db_session.commit()

    store = DashboardDataStore(db_session)
    scoped_dashboard = store.sales_dashboard(
        store_id=None,
        month="all",
        product_scope="精诚养车",
        product_type="all",
        trend_months=["2026-05"],
    )

    assert scoped_dashboard["product_scope"] == "精诚养车"
    assert scoped_dashboard["metrics"]["total_sales_order_count"] == 1
    assert [row["product_type"] for row in scoped_dashboard["product_rows"]] == [
        "268保养"
    ]

    mismatched_dashboard = store.sales_dashboard(
        store_id=None,
        month="all",
        product_scope="精诚养车",
        product_type="Other Service",
        trend_months=["2026-05"],
    )

    assert mismatched_dashboard["metrics"]["total_sales_order_count"] == 0
    assert mismatched_dashboard["product_rows"] == []


def test_error_message_sanitizer_redacts_sensitive_values_and_paths():
    assert sanitize_error_message("cookie=abc123") == "[redacted sensitive error]"
    assert (
        sanitize_error_message("failed reading C:\\Users\\admin\\Downloads\\data.csv")
        == "failed reading [path redacted]"
    )


def test_order_details_export_includes_all_matching_rows(db_session: Session):
    timestamp = datetime(2026, 5, 1, 8, tzinfo=timezone.utc)
    db_session.add_all(
        [
            DimStore(store_id="store_001", store_name="Store One", certified_subject_name="Subject One"),
            DimStore(store_id="store_002", store_name="Store Two", certified_subject_name="Subject Two"),
        ]
    )
    for index in range(501):
        db_session.add(
            SettlementOrderDetail(
                coupon_id=f"coupon_{index:03d}",
                order_id=f"order_{index:03d}",
                sku_id="sku_001",
                owner_account_id="acct_001",
                owner_account_name="Owner",
                product_type="basic_service",
                sale_store_id="store_001",
                sale_store_name="Store One",
                sale_time=timestamp,
                is_verified=True,
                verify_store_id="store_002",
                verify_store_name="Store Two",
                verify_time=timestamp,
                relation_type="cross_store",
                is_commissionable=True,
                is_refund_excluded=False,
                paid_amount_cent=10000,
                commission_rate=Decimal("0.1000"),
                receivable_commission_cent=1000,
                payable_commission_cent=1000,
                source_run_id="test-run",
                updated_at=timestamp,
            )
        )
    db_session.commit()

    store = DashboardDataStore(db_session)
    first_page = store.order_details({"page": 1, "page_size": 500})
    export_rows = list(csv.DictReader(io.StringIO(store.order_details_export_csv({}))))

    assert first_page["pagination"]["total"] == 501
    assert len(first_page["rows"]) == 500
    assert first_page["rows"][0]["sale_store_subject_name"] == "Subject One"
    assert first_page["rows"][0]["verify_store_subject_name"] == "Subject Two"
    assert first_page["rows"][0]["is_refund_excluded"] is False
    assert len(export_rows) == 501
    assert export_rows[0]["sale_store_subject_name"] == "Subject One"
    assert export_rows[0]["verify_store_subject_name"] == "Subject Two"
    assert export_rows[0]["is_refund_excluded"] == "False"
