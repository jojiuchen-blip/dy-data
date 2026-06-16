from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import AggStoreMonthlySettlement, DimSkuProductRule, JobRun  # noqa: E402
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


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
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
        json={"username": "admin", "password": "test-password"},
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
            "product_type": "",
            "commission_rate": 0.0,
            "is_service_product": True,
            "order_count": 1,
            "verified_coupon_count": 1,
        }
    ]


def test_admin_sku_rule_background_rebuild_materializes_settlement(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _load_unconfigured_cross_store_sku(db_session)
    run_settlement_job(
        db_session,
        job_id="before-admin-rule",
        source_run_id="before-admin-rule",
    )
    assert db_session.get(AggStoreMonthlySettlement, ("2026-06", "store-sale", "all")) is None

    job_id = "admin-sku-rules-background-test"
    db_session.merge(
        DimSkuProductRule(
            sku_id="sku-admin",
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
    monthly = db_session.get(AggStoreMonthlySettlement, ("2026-06", "store-sale", "all"))
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
    assert db_session.get(AggStoreMonthlySettlement, ("2026-06", "store-sale", "all")) is None
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

    rule = db_session.get(DimSkuProductRule, "sku-admin")
    assert rule is not None
    assert rule.product_type == "养车服务"

    job = db_session.get(JobRun, payload["job_id"])
    assert job is not None
    assert job.status == "queued"
    assert job.job_name == "settlement_rebuild"
    assert job.metadata_json["trigger"] == "admin_sku_rules"
    assert db_session.get(AggStoreMonthlySettlement, ("2026-06", "store-sale", "all")) is None
