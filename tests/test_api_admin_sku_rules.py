from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import (  # noqa: E402
    AggStoreMonthlySettlement,
    DimNonCommissionOwnerAccount,
    DimSkuProductRule,
    JobRun,
)
from dy_api.routes import admin as admin_routes  # noqa: E402
from apps.worker.repositories import (  # noqa: E402
    queue_job_run,
    upsert_aweme_binding,
    upsert_order_coupon,
    upsert_raw_order,
    upsert_store,
    upsert_store_poi_mapping,
    upsert_verify_record,
)
from apps.worker.settlement import run_settlement_job  # noqa: E402


def _dt(day: int) -> datetime:
    return datetime(2026, 6, day, 10, 0, tzinfo=timezone.utc)


def _monthly_projection(
    session: Session, month: str, store_id: str, product_type: str
) -> AggStoreMonthlySettlement | None:
    return session.scalar(
        select(AggStoreMonthlySettlement).where(
            AggStoreMonthlySettlement.month == month,
            AggStoreMonthlySettlement.store_id == store_id,
            AggStoreMonthlySettlement.product_scope == "all",
            AggStoreMonthlySettlement.product_type == product_type,
        )
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


def _load_unconfigured_cross_store_sku(session: Session) -> None:
    upsert_store(session, "store-sale", "Sale Store")
    upsert_store(session, "store-verify", "Verify Store")
    upsert_store_poi_mapping(session, "store-verify", "poi-verify")
    upsert_aweme_binding(
        session,
        "store-sale:dy-sale:poi-sale",
        douyin_nickname="Sale Owner",
        account_id="store-sale",
        account_name="Sale Store",
        poi_id="poi-sale",
        binding_status="认证成功",
    )
    upsert_raw_order(
        session,
        "order-sku-admin",
        sku_id="sku-admin",
        product_name="Admin Configurable Product",
        pay_time=_dt(1),
        owner_account_name="Sale Owner",
        paid_amount_cent=10000,
    )
    upsert_order_coupon(
        session,
        "coupon-sku-admin",
        "order-sku-admin",
        coupon_status="fulfilled",
    )
    upsert_verify_record(
        session,
        "verify-sku-admin",
        coupon_id="coupon-sku-admin",
        verify_status="valid",
        verify_time=_dt(2),
        poi_id="poi-verify",
        sku_id="sku-admin",
        product_name="Admin Configurable Product",
        paid_amount_cent=10000,
    )
    session.commit()


def test_admin_sku_rules_require_login(client: TestClient) -> None:
    response = client.get("/api/v1/admin/sku-rules")

    assert response.status_code == 401


def test_admin_sku_rule_lookup_requires_login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/admin/sku-rules/lookup",
        json={"sku_ids": ["sku-admin"]},
    )

    assert response.status_code == 401


def test_admin_can_list_sku_rules_from_raw_data(
    client: TestClient, db_session: Session
) -> None:
    _load_unconfigured_cross_store_sku(db_session)
    _login(client)

    response = client.get("/api/v1/admin/sku-rules")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["pagination"]["total"] == 1
    assert payload["rows"] == [
        {
            "sku_id": "sku-admin",
            "product_name": "Admin Configurable Product",
            "product_scope": "",
            "product_type": "",
            "commission_rate": 0.0,
            "is_service_product": True,
            "order_count": 1,
            "verified_coupon_count": 1,
        }
    ]


def test_admin_can_lookup_exact_sku_rules_in_input_order(
    client: TestClient, db_session: Session
) -> None:
    _load_unconfigured_cross_store_sku(db_session)
    db_session.merge(
        DimSkuProductRule(
            sku_id="sku-config-only",
            product_name="Configured Product",
            product_scope="",
            product_type="Configured Type",
            commission_rate=Decimal("0.2500"),
            is_service_product=False,
        )
    )
    db_session.commit()
    _login(client)

    response = client.post(
        "/api/v1/admin/sku-rules/lookup",
        json={
            "sku_ids": [
                "sku-config-only",
                " sku-admin ",
                "missing-sku",
                "sku-admin",
                "SKU-ADMIN",
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert [row["sku_id"] for row in payload["rows"]] == [
        "sku-config-only",
        "sku-admin",
    ]
    assert payload["rows"][0] == {
        "sku_id": "sku-config-only",
        "product_name": "Configured Product",
        "product_scope": "",
        "product_type": "Configured Type",
        "commission_rate": 0.25,
        "is_service_product": False,
        "order_count": 0,
        "verified_coupon_count": 0,
    }
    assert payload["missing_sku_ids"] == ["missing-sku", "SKU-ADMIN"]
    assert payload["duplicate_sku_ids"] == ["sku-admin"]


def test_admin_sku_rules_include_product_scope_from_rule_table(
    client: TestClient, db_session: Session
) -> None:
    db_session.merge(
        DimSkuProductRule(
            sku_id="1834808062911500",
            product_name="268 Maintenance",
            product_scope="精诚养车",
            product_type="268保养",
            commission_rate=Decimal("0.1000"),
            is_service_product=True,
        )
    )
    db_session.commit()
    _login(client)

    response = client.get("/api/v1/admin/sku-rules?q=1834808062911500")

    assert response.status_code == 200
    row = response.json()["data"]["rows"][0]
    assert row["product_scope"] == "精诚养车"
    assert row["product_type"] == "268保养"


def test_admin_sku_rules_can_filter_by_product_scope(
    client: TestClient, db_session: Session
) -> None:
    _load_unconfigured_cross_store_sku(db_session)
    db_session.merge(
        DimSkuProductRule(
            sku_id="1834808062911500",
            product_name="268 Maintenance",
            product_scope="精诚养车",
            product_type="268保养",
            commission_rate=Decimal("0.1000"),
            is_service_product=True,
        )
    )
    db_session.commit()
    _login(client)

    response = client.get("/api/v1/admin/sku-rules?product_scope=精诚")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["pagination"]["total"] == 1
    assert payload["rows"][0]["sku_id"] == "1834808062911500"
    assert payload["rows"][0]["product_scope"] == "精诚养车"


def test_admin_sku_rule_lookup_rejects_more_than_500_sku_ids(
    client: TestClient,
) -> None:
    _login(client)

    response = client.post(
        "/api/v1/admin/sku-rules/lookup",
        json={"sku_ids": [f"sku-{index}" for index in range(501)]},
    )

    assert response.status_code == 422


def test_admin_sku_rule_background_rebuild_materializes_settlement(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load_unconfigured_cross_store_sku(db_session)
    run_settlement_job(
        db_session,
        job_id="before-admin-rule",
        source_run_id="before-admin-rule",
    )
    assert _monthly_projection(db_session, "2026-06", "store-sale", "all") is None

    job_id = "admin-sku-rules-background-test"
    db_session.merge(
        DimSkuProductRule(
            sku_id="sku-admin",
            product_scope="精诚养车",
            product_type="养车服务",
            commission_rate=Decimal("0.1000"),
            is_service_product=True,
        )
    )
    queue_job_run(
        db_session,
        job_id,
        "settlement_rebuild",
        metadata_json={"trigger": "admin_sku_rules"},
    )
    db_session.commit()

    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(admin_routes, "get_session_factory", lambda: factory)

    admin_routes.run_admin_sku_rule_rebuild_job(job_id=job_id)

    db_session.expire_all()
    monthly = _monthly_projection(db_session, "2026-06", "store-sale", "all")
    assert monthly is not None
    assert monthly.estimated_receivable_commission_cent == 1000
    job = db_session.get(JobRun, job_id)
    assert job is not None
    assert job.status == "success"


def test_admin_bulk_save_rules_queues_settlement_rebuild(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _load_unconfigured_cross_store_sku(db_session)
    run_settlement_job(
        db_session,
        job_id="before-admin-queued-rule",
        source_run_id="before-admin-queued-rule",
    )
    assert _monthly_projection(db_session, "2026-06", "store-sale", "all") is None
    queued_jobs: list[str] = []

    def fake_rebuild_job(*, job_id: str) -> None:
        queued_jobs.append(job_id)

    monkeypatch.setattr(
        admin_routes,
        "run_admin_sku_rule_rebuild_job",
        fake_rebuild_job,
        raising=False,
    )

    _login(client)
    response = client.put(
        "/api/v1/admin/sku-rules",
        json={
            "rules": [
                {
                    "sku_id": "sku-admin",
                    "product_scope": "精诚养车",
                    "product_type": "养车服务",
                    "commission_rate": 0.1,
                    "is_service_product": True,
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["updated_count"] == 1
    assert payload["rebuild_status"] == "queued"
    assert payload["job_id"].startswith("admin-sku-rules-")
    assert queued_jobs == [payload["job_id"]]

    rule = db_session.scalar(
        select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-admin")
    )
    assert rule is not None
    assert rule.product_scope == "精诚养车"
    assert rule.product_type == "养车服务"

    job = db_session.get(JobRun, payload["job_id"])
    assert job is not None
    assert job.status == "queued"
    assert job.job_name == "settlement_rebuild"
    assert job.metadata_json["trigger"] == "admin_sku_rules"
    assert _monthly_projection(db_session, "2026-06", "store-sale", "all") is None


def test_admin_bulk_save_updates_existing_sku_rule_without_duplicates(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        admin_routes,
        "run_admin_sku_rule_rebuild_job",
        lambda *, job_id: None,
        raising=False,
    )
    _login(client)

    first_response = client.put(
        "/api/v1/admin/sku-rules",
        json={
            "rules": [
                {
                    "sku_id": "stable-sku",
                    "product_scope": "initial-scope",
                    "product_type": "initial-type",
                    "commission_rate": 0.1,
                    "is_service_product": True,
                }
            ]
        },
    )
    second_response = client.put(
        "/api/v1/admin/sku-rules",
        json={
            "rules": [
                {
                    "sku_id": "stable-sku",
                    "product_scope": "updated-scope",
                    "product_type": "updated-type",
                    "commission_rate": 0.2,
                    "is_service_product": False,
                }
            ]
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    db_session.expire_all()
    rule = db_session.scalar(
        select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "stable-sku")
    )
    assert rule is not None
    assert rule.product_scope == "updated-scope"
    assert rule.product_type == "updated-type"
    assert db_session.scalar(
        select(func.count())
        .select_from(DimSkuProductRule)
        .where(DimSkuProductRule.sku_id == "stable-sku")
    ) == 1


def test_admin_can_replace_non_commission_owner_accounts_and_queue_rebuild(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued_jobs: list[str] = []

    def fake_rebuild_job(*, job_id: str) -> None:
        queued_jobs.append(job_id)

    monkeypatch.setattr(
        admin_routes,
        "run_admin_sku_rule_rebuild_job",
        fake_rebuild_job,
        raising=False,
    )

    _login(client)
    response = client.put(
        "/api/v1/admin/non-commission-owner-accounts",
        json={
            "accounts": [
                {"owner_account_name": "比亚迪汽车精品"},
                {"owner_account_name": " 精诚养车--比亚迪服务于全品牌 "},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["updated_count"] == 2
    assert payload["rebuild_status"] == "queued"
    assert payload["job_id"].startswith("admin-non-commission-accounts-")
    assert queued_jobs == [payload["job_id"]]

    rows = {
        row["owner_account_name"]: row
        for row in client.get("/api/v1/admin/non-commission-owner-accounts").json()["data"]["rows"]
    }
    assert set(rows) == {"比亚迪汽车精品", "精诚养车--比亚迪服务于全品牌"}
    assert rows["精诚养车--比亚迪服务于全品牌"]["is_active"] is True

    stored = db_session.get(
        DimNonCommissionOwnerAccount,
        rows["精诚养车--比亚迪服务于全品牌"]["normalized_owner_account_name"],
    )
    assert stored is not None
    assert stored.owner_account_name == "精诚养车--比亚迪服务于全品牌"

    job = db_session.get(JobRun, payload["job_id"])
    assert job is not None
    assert job.status == "queued"
    assert job.metadata_json["trigger"] == "admin_non_commission_owner_accounts"


def test_commission_rules_summary_requires_login_and_filters_zero_rate_skus(
    client: TestClient,
    db_session: Session,
) -> None:
    db_session.add(
        DimNonCommissionOwnerAccount(
            normalized_owner_account_name="official",
            owner_account_name="官方账号",
            is_active=True,
        )
    )
    db_session.add(
        DimSkuProductRule(
            sku_id="sku-commissionable",
            product_name="分佣商品",
            product_scope="精诚养车",
            product_type="精诚养车",
            commission_rate=Decimal("0.1000"),
            is_service_product=True,
        )
    )
    db_session.add(
        DimSkuProductRule(
            sku_id="sku-zero",
            product_name="零比例商品",
            product_scope="精诚养车",
            product_type="精诚养车",
            commission_rate=Decimal("0.0000"),
            is_service_product=True,
        )
    )
    db_session.commit()

    _login(client)
    response = client.get("/api/v1/commission-rules/summary")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["non_commission_owner_accounts"] == ["官方账号"]
    assert data["commission_skus"] == [
        {
            "sku_id": "sku-commissionable",
            "product_name": "分佣商品",
            "commission_rate": 0.1,
        }
    ]
