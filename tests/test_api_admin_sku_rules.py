from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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
    JobEvent,
    JobRun,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
)
from dy_api.routes import admin as admin_routes  # noqa: E402
from dy_api.routes import _settlement_jobs as settlement_jobs  # noqa: E402
from apps.worker.repositories import (  # noqa: E402
    finish_job_run,
    queue_job_run,
    start_job_run,
    upsert_aweme_binding,
    upsert_order_coupon,
    upsert_raw_order,
    upsert_store,
    upsert_store_poi_mapping,
    upsert_verify_record,
)
from apps.worker.settlement import run_settlement_job  # noqa: E402
from apps.worker import settlement_rebuild  # noqa: E402


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


def test_admin_rebuild_publishes_lineage_for_single_store_readers(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
    db_session.add(
        SettlementProjectionGeneration(
            generation_id="admin-lineage-base",
            base_generation_id=None,
            generation_kind="legacy_root",
            compaction_base_generation_id=None,
            projection_name="settlement",
            state="published",
            input_fingerprint="0" * 64,
            lineage_depth=0,
            estimated_write_rows=0,
            estimated_write_bytes=0,
            estimated_wal_bytes=0,
            estimated_disk_headroom_bytes=0,
            checkpoint_json={"phase": "published"},
            last_key=None,
            manifest_checksum="1" * 64,
            source_input_json={},
            published_at=now,
            created_at=now,
        )
    )
    db_session.add(
        SettlementProjectionActive(
            projection_name="settlement",
            generation_id="admin-lineage-base",
        )
    )
    db_session.add(
        AggStoreMonthlySettlement(
            month="2026-08",
            store_id="lineage-store",
            product_scope="all",
            product_type="all",
            sales_order_count=1,
            sales_amount_cent=100,
            verified_order_count=1,
            verified_amount_cent=100,
            promotion_base_cent=100,
            promotion_original_fee_cent=10,
            promotion_adjustment_fee_cent=0,
            promotion_net_fee_cent=10,
            management_base_cent=100,
            management_original_fee_cent=2,
            management_adjustment_fee_cent=0,
            management_net_fee_cent=2,
            statement_status=1,
            projection_run_id="legacy",
            estimated_receivable_commission_cent=10,
            commissionable_total_cent=100,
            estimated_payable_commission_cent=2,
        )
    )
    job_id = "admin-lineage-refresh-test"
    queue_job_run(
        db_session,
        job_id,
        "settlement_rebuild",
        metadata_json={"trigger": "admin_sku_fee_rules"},
    )
    db_session.commit()

    def fake_run_settlement_job(
        session: Session, *, job_id: str, source_run_id: str
    ) -> None:
        start_job_run(
            session,
            job_id,
            "settlement_rebuild",
            metadata_json={"source_run_id": source_run_id},
        )
        finish_job_run(session, job_id, status="success", success_count=1)

    def fake_build_sparse_overlay(factory, **kwargs):
        with factory() as session:
            session.add(
                SettlementProjectionGeneration(
                    generation_id=kwargs["generation_id"],
                    base_generation_id=kwargs["base_generation_id"],
                    generation_kind="lineage",
                    compaction_base_generation_id=None,
                    projection_name="settlement",
                    state="ready",
                    input_fingerprint=kwargs["input_fingerprint"],
                    lineage_depth=1,
                    estimated_write_rows=1,
                    estimated_write_bytes=1,
                    estimated_wal_bytes=1,
                    estimated_disk_headroom_bytes=0,
                    checkpoint_json={"phase": "ready"},
                    last_key=None,
                    manifest_checksum="f" * 64,
                    source_job_id=job_id,
                    source_input_json={},
                    created_at=now,
                )
            )
            session.commit()
        return SimpleNamespace(manifest_checksum="f" * 64, manifest_count=1, row_count=1)

    monkeypatch.setattr(
        settlement_rebuild, "run_settlement_job", fake_run_settlement_job
    )
    monkeypatch.setattr(
        settlement_rebuild,
        "build_settlement_sparse_overlay",
        fake_build_sparse_overlay,
    )
    factory = sessionmaker(
        bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True
    )

    settlement_jobs.run_settlement_rebuild_job(job_id=job_id, factory=factory)

    db_session.expire_all()
    pointer = db_session.get(SettlementProjectionActive, "settlement")
    assert pointer is not None
    assert pointer.generation_id == f"settlement-admin-rebuild:{job_id}"
    generation = db_session.get(SettlementProjectionGeneration, pointer.generation_id)
    assert generation is not None
    assert generation.state == "published"
    assert generation.source_job_id == job_id
    event = db_session.scalar(
        select(JobEvent).where(
            JobEvent.job_id == job_id,
            JobEvent.event_type == "settlement_projection_published",
        )
    )
    assert event is not None


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
