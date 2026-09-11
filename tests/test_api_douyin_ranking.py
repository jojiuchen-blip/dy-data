from __future__ import annotations

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import DimStore, DimStoreOrgAssignment  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402


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


def test_douyin_ranking_route_returns_camel_case_contract_and_requires_a03(
    client: TestClient, db_session: Session
) -> None:
    db_session.add(
        DimStore(
            store_id="store-1",
            store_name="门店一",
            service_store_code="SVC-001",
            is_active=True,
        )
    )
    db_session.add(
        DimStoreOrgAssignment(
            service_store_code="SVC-001",
            service_center_name="中心一",
            district_name="大区一",
            area_name="区域一",
        )
    )
    db_session.commit()
    from apps.api.dy_api.ranking_schema_v1 import metadata
    from apps.api.dy_api.ranking_configuration import publish_configuration, DATA_START
    metadata.create_all(db_session.bind)
    publish_configuration(db_session, organizations=[dict(store_id="store-1", service_store_code="SVC-001",
        store_name="门店一", group_name="集团一", service_center_name="中心一",
        district_name="大区一", area_name="区域一")], eligible_codes=["SVC-001"], effective_from=DATA_START)
    db_session.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert login.status_code == 200
    response = client.get(
        "/api/v1/dashboard/douyin-ranking",
        params={"periodStart": "2026-09-01", "periodEnd": "2026-09-10"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["level"] == "service_center"
    assert payload["data"]["rows"][0]["name"] == "中心一"
    assert payload["data"]["rows"][0]["orderCount"] == 0
    assert payload["data"]["dataMode"] == "business"
    assert payload["data"]["snapshotId"].startswith("business-")
    assert payload["definitions"][0]["key"] == "order_count"


def test_ranking_database_failure_returns_safe_retry_response(client, monkeypatch, db_session):
    from sqlalchemy.exc import OperationalError
    from dy_api.routes import dashboard
    assert client.post('/api/v1/auth/login', json={
        'username':'system-admin', 'password':'test-password'}).status_code == 200
    def fail(*args, **kwargs):
        raise OperationalError('private SQL statement', {'secret':'private parameter'},
                               Exception('canceling statement due to statement timeout'))
    monkeypatch.setattr(dashboard, 'ensure_business_snapshot', fail)
    with TestClient(client.app, raise_server_exceptions=False) as probe:
        probe.cookies.update(client.cookies)
        response = probe.get('/api/v1/dashboard/douyin-ranking', params={
            'periodStart':'2026-09-01', 'periodEnd':'2026-09-11'})
    assert response.status_code == 503
    assert 'private' not in response.text
    assert 'SQL' not in response.text
    assert 'RANKING_QUERY_UNAVAILABLE' in response.text


def test_highest_admin_can_upload_douyin_store_org_csv_snapshot(
    client: TestClient, db_session: Session
) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert login.status_code == 200
    response = client.post(
        "/api/v1/admin/sync/douyin-store-org",
        files={
            "file": (
                "mapping.csv",
                "服务店编码,服务店名称,服务中心,大区,区域\nSVC-001,门店一,中心一,大区一,区域一\n".encode(
                    "utf-8-sig"
                ),
                "text/csv",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["updated"] == 1
    row = db_session.get(DimStoreOrgAssignment, "SVC-001")
    assert row is not None
    assert row.is_active is True


def test_highest_admin_uploads_versioned_organization_and_eligibility(client, db_session):
    from apps.api.dy_api.models import DimStorePoiMapping
    from apps.api.dy_api.ranking_schema_v1 import metadata, org_history, eligibility
    from sqlalchemy import select, func
    metadata.create_all(db_session.bind)
    db_session.add(DimStore(store_id="store-1", store_name="门店一"))
    db_session.flush()
    db_session.add(DimStorePoiMapping(store_id="store-1", poi_id="POI-1", is_primary=True))
    db_session.commit()
    assert client.post("/api/v1/auth/login", json={"username":"system-admin", "password":"test-password"}).status_code == 200
    files = {
        "organization_file": ("org.csv", "门店名称,所属账户关联poi_ID,服务店编码,服务店名称,是否为直营店,所属集团,集团编码,服务中心,大区,区域,数据来源\n门店一,POI-1,SVC-001,门店一,否,集团一,G1,中心一,大区一,区域一,测试\n".encode("utf-8"), "text/csv"),
        "eligibility_file": ("elig.csv", "所属账户关联poi_ID,门店名称\nPOI-1,门店一\n".encode("utf-8"), "text/csv"),
    }
    first = client.post("/api/v1/admin/sync/douyin-ranking-configuration", files=files)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["store_count"] == 1
    assert first.json()["data"]["eligible_store_count"] == 1
    assert first.json()["data"]["changed"] is True
    repeat = client.post("/api/v1/admin/sync/douyin-ranking-configuration", files=files)
    assert repeat.status_code == 200
    assert repeat.json()["data"]["changed"] is False
    assert db_session.scalar(select(func.count()).select_from(org_history)) == 1
    assert db_session.scalar(select(func.count()).select_from(eligibility)) == 1


def test_ranking_configuration_upload_requires_authentication(client):
    assert client.post("/api/v1/admin/sync/douyin-ranking-configuration").status_code == 401
