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
    assert data["stores"] == [{"store_id": "store_001", "store_name": "Store One"}]
    assert data["product_scopes"] == ["all", "精诚养车"]
    assert data["product_scope_type_map"] == {"精诚养车": ["basic_service"]}
    assert data["product_types"] == ["all", "basic_service"]
    assert "latest_job" not in data


def test_dashboard_contract_responses_do_not_expose_deferred_fields(
    client: TestClient,
):
    _login(client)
    ranking = client.get("/api/v1/dashboard/store-ranking?month=2026-05")
    settlement = client.get(
        "/api/v1/stores/store_001/monthly-settlement?month=2026-05"
    )
    sales = client.get(
        "/api/v1/dashboard/sales?store_id=store_001&month=all&trend_months=2026-05"
    )
    details = client.get("/api/v1/order-details?page=1&page_size=50")

    assert ranking.status_code == 200
    ranking_payload = ranking.json()
    assert ranking_payload["data"]["rows"][0]["sales_order_count"] == 3
    assert ranking_payload["data"]["totals"]["sales_order_count"] == 30
    ranking_definitions = {
        definition["key"]: definition for definition in ranking_payload["definitions"]
    }
    assert ranking_definitions["sales_order_count"]["label"] == "销售订单数量"
    assert "顶部数字" in ranking_definitions["sales_order_count"]["description"]
    assert ranking_definitions["self_verify_income_cent"]["label"] == "核销收入"

    assert settlement.status_code == 200
    settlement_payload = settlement.json()
    settlement_definitions = {
        definition["key"]: definition for definition in settlement_payload["definitions"]
    }
    assert (
        settlement_definitions["estimated_receivable_commission_cent"]["label"]
        == "预计应收分佣"
    )
    assert "commissionable_total_cent" not in settlement_definitions
    assert (
        "按当前规则测算的参考额"
        in settlement_definitions["estimated_payable_commission_cent"]["description"]
    )
    assert (
        settlement_payload["data"]["metrics"][
            "estimated_receivable_commission_cent"
        ]
        == 1680
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
    assert "is_refund_excluded=true" in sales_definitions["total_sales_order_count"]["description"]
    assert deferred_field("refund", "amount", "cent") not in sales.text

    assert details.status_code == 200
    detail_row = details.json()["data"]["rows"][0]
    assert detail_row["coupon_id"] == "coupon_001"
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
