from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402
from apps.api.dy_api.models import UserFeedbackSubmission  # noqa: E402


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


def test_feedback_requires_login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/feedback",
        json={"category": "experience", "content": "筛选项可以更紧凑一些。"},
    )

    assert response.status_code == 401


def test_logged_in_user_can_submit_feedback(
    client: TestClient, db_session: Session
) -> None:
    _login(client)

    response = client.post(
        "/api/v1/feedback",
        json={
            "category": "feature",
            "content": "  希望线索明细支持批量导出。  ",
            "contact": "  门店运营 张三  ",
            "page_path": "/clues/details",
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["category"] == "feature"
    assert payload["status"] == "new"
    assert payload["feedback_id"]

    rows = db_session.execute(select(UserFeedbackSubmission)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.feedback_id == payload["feedback_id"]
    assert row.category == "feature"
    assert row.content == "希望线索明细支持批量导出。"
    assert row.contact == "门店运营 张三"
    assert row.page_path == "/clues/details"
    assert row.username == "system-admin"
    assert row.user_role == "admin"
    assert row.status == "new"


def test_feedback_rejects_empty_content(client: TestClient) -> None:
    _login(client)

    response = client.post(
        "/api/v1/feedback",
        json={"category": "experience", "content": "   "},
    )

    assert response.status_code == 422


def test_admin_can_list_filter_and_update_feedback_status(
    client: TestClient, db_session: Session
) -> None:
    _login(client)
    first = client.post(
        "/api/v1/feedback",
        json={
            "category": "feature",
            "content": "希望增加后台建议列表。",
            "contact": "ops-a",
            "page_path": "/ranking",
        },
    )
    second = client.post(
        "/api/v1/feedback",
        json={
            "category": "data",
            "content": "线索统计数字需要复核。",
            "contact": "ops-b",
            "page_path": "/clues",
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200

    response = client.get(
        "/api/v1/admin/feedback",
        params={"status": "new", "category": "feature", "q": "后台"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["pagination"]["total"] == 1
    assert payload["status_counts"]["new"] == 1
    row = payload["rows"][0]
    assert row["category"] == "feature"
    assert row["content"] == "希望增加后台建议列表。"
    assert row["contact"] == "ops-a"
    assert row["page_path"] == "/ranking"
    assert row["username"] == "system-admin"
    assert row["status"] == "new"

    updated = client.put(
        f"/api/v1/admin/feedback/{row['feedback_id']}/status",
        json={"status": "resolved"},
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["status"] == "resolved"
    stored = db_session.get(UserFeedbackSubmission, row["feedback_id"])
    assert stored is not None
    assert stored.status == "resolved"


def test_admin_feedback_rejects_invalid_filters(client: TestClient) -> None:
    _login(client)

    invalid_status = client.get("/api/v1/admin/feedback?status=done")
    invalid_category = client.get("/api/v1/admin/feedback?category=bug")

    assert invalid_status.status_code == 422
    assert invalid_category.status_code == 422
