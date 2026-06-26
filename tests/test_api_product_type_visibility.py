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
    AggStoreRanking,
    ClueAssignmentRound,
    ClueCenterOrder,
    DimStore,
    SettlementOrderDetail,
    User,
    UserStoreScope,
)
from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402


JINGCHENG_PRODUCT = "精诚养车"
HIDDEN_PRODUCT = "其他服务"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    monkeypatch.delenv("DY_SUPER_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("DY_ADMIN_PASSWORD_HASH", raising=False)

    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _dt(day: int) -> datetime:
    return datetime(2026, 6, day, 8, tzinfo=timezone.utc)


def _login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert response.status_code == 200


def _seed_product_visibility_data(session: Session) -> None:
    session.add_all(
        [
            DimStore(store_id="store-1", store_name="Store One", is_active=True),
            DimStore(store_id="store-2", store_name="Store Two", is_active=True),
            AggStoreRanking(
                month="2026-06",
                product_type="all",
                store_id="store-1",
                store_name="Store One",
                sales_order_count=11,
                self_sold_self_verified_count=1,
                self_sold_other_verified_count=10,
                other_sold_self_verified_count=0,
                self_verify_income_cent=11000,
                effective_commission_income_cent=1100,
                updated_at=_dt(3),
            ),
            AggStoreRanking(
                month="2026-06",
                product_type=JINGCHENG_PRODUCT,
                store_id="store-1",
                store_name="Store One",
                sales_order_count=4,
                self_sold_self_verified_count=1,
                self_sold_other_verified_count=3,
                other_sold_self_verified_count=0,
                self_verify_income_cent=4000,
                effective_commission_income_cent=400,
                updated_at=_dt(3),
            ),
            AggStoreRanking(
                month="2026-06",
                product_type=HIDDEN_PRODUCT,
                store_id="store-1",
                store_name="Store One",
                sales_order_count=7,
                self_sold_self_verified_count=0,
                self_sold_other_verified_count=7,
                other_sold_self_verified_count=0,
                self_verify_income_cent=7000,
                effective_commission_income_cent=700,
                updated_at=_dt(3),
            ),
            AggStoreMonthlySettlement(
                month="2026-06",
                store_id="store-1",
                product_type="all",
                estimated_receivable_commission_cent=1100,
                commissionable_total_cent=11000,
                estimated_payable_commission_cent=0,
                updated_at=_dt(3),
            ),
            AggStoreMonthlySettlement(
                month="2026-06",
                store_id="store-1",
                product_type=JINGCHENG_PRODUCT,
                estimated_receivable_commission_cent=400,
                commissionable_total_cent=4000,
                estimated_payable_commission_cent=0,
                updated_at=_dt(3),
            ),
            AggStoreMonthlySettlement(
                month="2026-06",
                store_id="store-1",
                product_type=HIDDEN_PRODUCT,
                estimated_receivable_commission_cent=700,
                commissionable_total_cent=7000,
                estimated_payable_commission_cent=0,
                updated_at=_dt(3),
            ),
            SettlementOrderDetail(
                coupon_id="coupon-visible",
                order_id="order-visible",
                sku_id="sku-visible",
                owner_account_id="owner",
                owner_account_name="Owner",
                product_type=JINGCHENG_PRODUCT,
                sale_store_id="store-1",
                sale_store_name="Store One",
                sale_time=_dt(1),
                is_verified=True,
                verify_store_id="store-2",
                verify_store_name="Store Two",
                verify_time=_dt(2),
                relation_type="cross_store",
                is_commissionable=True,
                is_refund_excluded=False,
                paid_amount_cent=4000,
                commission_rate=Decimal("0.1000"),
                receivable_commission_cent=400,
                payable_commission_cent=0,
                source_run_id="test",
                updated_at=_dt(3),
            ),
            SettlementOrderDetail(
                coupon_id="coupon-hidden",
                order_id="order-hidden",
                sku_id="sku-hidden",
                owner_account_id="owner",
                owner_account_name="Owner",
                product_type=HIDDEN_PRODUCT,
                sale_store_id="store-1",
                sale_store_name="Store One",
                sale_time=_dt(1),
                is_verified=True,
                verify_store_id="store-2",
                verify_store_name="Store Two",
                verify_time=_dt(2),
                relation_type="cross_store",
                is_commissionable=True,
                is_refund_excluded=False,
                paid_amount_cent=7000,
                commission_rate=Decimal("0.1000"),
                receivable_commission_cent=700,
                payable_commission_cent=0,
                source_run_id="test",
                updated_at=_dt(3),
            ),
            ClueCenterOrder(
                order_id="clue-visible",
                source_clue_ids=["clue-visible-raw"],
                source_clue_count=1,
                canonical_clue_id="clue-visible-raw",
                lead_status="active",
                current_assignment_round_id="clue-visible-1",
                current_round_no=1,
                current_round_status="active_unfollowed",
                assigned_at=_dt(1),
                assigned_store_id="store-1",
                assigned_store_name="Store One",
                product_name="Visible Product",
                product_type=JINGCHENG_PRODUCT,
                follow_result="pending",
                is_followed=False,
                is_follow_success=False,
                is_self_store_verified=False,
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
            ClueAssignmentRound(
                assignment_round_id="clue-visible-1",
                order_id="clue-visible",
                round_no=1,
                assigned_at=_dt(1),
                assigned_store_id="store-1",
                assigned_store_name="Store One",
                follow_result="pending",
                is_followed=False,
                is_follow_success=False,
                round_status="active_unfollowed",
                is_self_store_verified=False,
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
            ClueCenterOrder(
                order_id="clue-hidden",
                source_clue_ids=["clue-hidden-raw"],
                source_clue_count=1,
                canonical_clue_id="clue-hidden-raw",
                lead_status="active",
                current_assignment_round_id="clue-hidden-1",
                current_round_no=1,
                current_round_status="active_unfollowed",
                assigned_at=_dt(1),
                assigned_store_id="store-1",
                assigned_store_name="Store One",
                product_name="Hidden Product",
                product_type=HIDDEN_PRODUCT,
                follow_result="pending",
                is_followed=False,
                is_follow_success=False,
                is_self_store_verified=False,
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
            ClueAssignmentRound(
                assignment_round_id="clue-hidden-1",
                order_id="clue-hidden",
                round_no=1,
                assigned_at=_dt(1),
                assigned_store_id="store-1",
                assigned_store_name="Store One",
                follow_result="pending",
                is_followed=False,
                is_follow_success=False,
                round_status="active_unfollowed",
                is_self_store_verified=False,
                created_at=_dt(1),
                updated_at=_dt(1),
            ),
        ]
    )
    session.commit()


def test_admin_can_limit_settlement_and_clue_data_by_product_type(
    client: TestClient, db_session: Session
) -> None:
    _seed_product_visibility_data(db_session)
    _login_admin(client)

    initial = client.get("/api/v1/admin/product-type-visibility")
    assert initial.status_code == 200
    assert initial.json()["data"]["enabled"] is False
    assert initial.json()["data"]["visible_product_types"] == []
    assert initial.json()["data"]["default_product_type"] == "all"
    assert set(initial.json()["data"]["available_product_types"]) == {
        JINGCHENG_PRODUCT,
        HIDDEN_PRODUCT,
    }

    saved = client.put(
        "/api/v1/admin/product-type-visibility",
        json={
            "enabled": True,
            "visible_product_types": [JINGCHENG_PRODUCT],
            "default_product_type": JINGCHENG_PRODUCT,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["enabled"] is True
    assert saved.json()["data"]["visible_product_types"] == [JINGCHENG_PRODUCT]
    assert saved.json()["data"]["default_product_type"] == JINGCHENG_PRODUCT

    meta = client.get("/api/v1/meta/filters")
    assert meta.status_code == 200
    assert meta.json()["data"]["product_types"] == ["all", JINGCHENG_PRODUCT]
    assert meta.json()["data"]["default_product_type"] == JINGCHENG_PRODUCT

    ranking = client.get(
        "/api/v1/dashboard/store-ranking",
        params={"month": "2026-06", "product_type": "all"},
    )
    assert ranking.status_code == 200
    assert ranking.json()["data"]["totals"]["sales_order_count"] == 4
    assert ranking.json()["data"]["rows"][0]["sales_order_count"] == 4

    settlement = client.get(
        "/api/v1/stores/store-1/monthly-settlement",
        params={"month": "2026-06", "product_type": "all"},
    )
    assert settlement.status_code == 200
    assert settlement.json()["data"]["metrics"]["commissionable_total_cent"] == 4000
    receivable_rows = settlement.json()["data"]["tables"]["receivable_commissions"]
    assert [row["product_type"] for row in receivable_rows] == [JINGCHENG_PRODUCT]

    details = client.get("/api/v1/order-details", params={"page": 1, "page_size": 50})
    assert details.status_code == 200
    assert [row["coupon_id"] for row in details.json()["data"]["rows"]] == [
        "coupon-visible"
    ]

    clue_filters = client.get("/api/v1/clues/filters")
    assert clue_filters.status_code == 200
    assert clue_filters.json()["data"]["product_types"] == [JINGCHENG_PRODUCT]
    assert clue_filters.json()["data"]["default_product_type"] == JINGCHENG_PRODUCT

    clue_overview = client.get("/api/v1/clues/overview")
    assert clue_overview.status_code == 200
    assert clue_overview.json()["data"]["total_clues"] == 1

    clue_rounds = client.get("/api/v1/clues/assignment-rounds")
    assert clue_rounds.status_code == 200
    assert [row["order_id"] for row in clue_rounds.json()["data"]["rows"]] == [
        "clue-visible"
    ]

    hidden_detail = client.get("/api/v1/clues/orders/clue-hidden")
    assert hidden_detail.status_code == 404


def test_product_type_visibility_requires_admin(
    client: TestClient, db_session: Session
) -> None:
    _seed_product_visibility_data(db_session)
    db_session.add_all(
        [
            User(
                user_id="store-user",
                username="store-user",
                external_account_id="store-1",
                display_name="Store User",
                role="store",
                status="active",
                is_initialized=True,
                password_hash=hash_password_pbkdf2("store-password"),
            ),
            UserStoreScope(user_id="store-user", store_id="store-1"),
        ]
    )
    db_session.commit()

    assert client.get("/api/v1/admin/product-type-visibility").status_code == 401
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "store-user", "password": "store-password"},
    )
    assert login.status_code == 200

    response = client.put(
        "/api/v1/admin/product-type-visibility",
        json={"enabled": True, "visible_product_types": [JINGCHENG_PRODUCT]},
    )
    assert response.status_code == 403


def test_product_type_visibility_rejects_hidden_default_product_type(
    client: TestClient, db_session: Session
) -> None:
    _seed_product_visibility_data(db_session)
    _login_admin(client)

    response = client.put(
        "/api/v1/admin/product-type-visibility",
        json={
            "enabled": True,
            "visible_product_types": [JINGCHENG_PRODUCT],
            "default_product_type": HIDDEN_PRODUCT,
        },
    )

    assert response.status_code == 422
