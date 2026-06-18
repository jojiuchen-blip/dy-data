from __future__ import annotations

import sys
from datetime import datetime, timezone
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
    SettlementOrderDetail,
    User,
    UserStoreScope,
)
from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402


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
            DimStore(store_id="store-1", store_name="Store One", is_active=True),
            DimStore(store_id="store-2", store_name="Store Two", is_active=True),
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


def test_store_user_permissions_are_enforced(client: TestClient) -> None:
    assert client.get("/api/v1/order-details").status_code == 401
    _login_store(client)

    own_store = client.get("/api/v1/stores/store-1/monthly-settlement?month=2026-05")
    assert own_store.status_code == 200

    other_store = client.get("/api/v1/stores/store-2/monthly-settlement?month=2026-05")
    assert other_store.status_code == 403

    details = client.get("/api/v1/order-details?page=1&page_size=50")
    assert details.status_code == 200
    rows = details.json()["data"]["rows"]
    assert [row["order_id"] for row in rows] == ["order-sale"]


def test_viewer_can_see_all_data_but_cannot_enter_admin(client: TestClient) -> None:
    _login_viewer(client)

    other_store = client.get("/api/v1/stores/store-2/monthly-settlement?month=2026-05")
    assert other_store.status_code == 200

    details = client.get("/api/v1/order-details?page=1&page_size=50")
    assert details.status_code == 200
    assert {row["order_id"] for row in details.json()["data"]["rows"]} == {
        "order-sale",
        "order-other",
    }

    admin_accounts = client.get("/api/v1/admin/accounts")
    assert admin_accounts.status_code == 403
