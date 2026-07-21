from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.auth import AuthContext  # noqa: E402
from dy_api.cli_auth import get_current_cli_user  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_data_store  # noqa: E402


class AuditStore:
    available = True

    def list_stores(self, scope_store_ids=None):
        return [{"store_id": "store-1", "store_name": "Store One"}]

    def clue_store_follow_up_summary(self, **kwargs):
        return [
            {
                "store_id": "store-1",
                "store_name": "Store One",
                "total_count": 0,
                "pending_count": 0,
                "followed_count": 0,
                "other_status_count": 0,
                "action_followed_count": 0,
                "effective_followed_count": 0,
                "system_follow_up_rate": 0,
                "action_follow_rate": 0,
            }
        ]


def _client(store=None) -> TestClient:
    app = create_app()
    auth = AuthContext(
        user_id="user-1",
        username="operator",
        display_name="Operator",
        role="store",
        store_ids=("store-1",),
        auth_type="user",
    )
    app.dependency_overrides[get_current_cli_user] = lambda: auth
    app.dependency_overrides[get_data_store] = lambda: store or AuditStore()
    return TestClient(app)


def _events(caplog) -> list[dict]:
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "dy_api.cli_audit" and record.message.startswith("{")
    ]


def test_cli_audit_uses_same_valid_request_id_and_only_logs_summary(
    caplog,
) -> None:
    caplog.set_level(logging.INFO, logger="dy_api.cli_audit")
    client = _client()

    response = client.get(
        "/api/v1/clues/store-follow-up-summary",
        headers={
            "X-Request-ID": "req_client-123",
            "X-DyData-CLI-Version": "0.1.0",
            "X-DyData-Command": "clues.follow-up-stats",
            "X-DyData-Schema-Version": "1.0",
            "Authorization": "Bearer never-log-this",
            "Cookie": "dy_session=never-log-this-either",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req_client-123"
    assert response.json()["meta"]["request_id"] == "req_client-123"
    [event] = _events(caplog)
    assert event == {
        "event": "cli_request",
        "request_id": "req_client-123",
        "user_id": "user-1",
        "auth_type": "user",
        "cli_version": "0.1.0",
        "command": "clues.follow-up-stats",
        "schema_version": "1.0",
        "date_range": [event["date_range"][0], event["date_range"][1]],
        "requested_store_ids": [],
        "effective_store_ids": ["store-1"],
        "returned_store_count": 1,
        "result": 200,
        "error_code": None,
        "duration_ms": event["duration_ms"],
    }
    assert event["date_range"][0] <= event["date_range"][1]
    assert isinstance(event["duration_ms"], float)
    rendered = json.dumps(event, ensure_ascii=False).lower()
    assert "never-log-this" not in rendered
    assert not {"authorization", "cookie", "token", "response"}.intersection(event)


def test_cli_audit_replaces_unsafe_request_id_and_logs_auth_error(caplog) -> None:
    caplog.set_level(logging.INFO, logger="dy_api.cli_audit")
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/cli/auth/status",
        headers={"X-Request-ID": "bad id\r\ninjected", "Authorization": "Bearer bad"},
    )

    assert response.status_code == 401
    request_id = response.headers["x-request-id"]
    assert request_id.startswith("req_")
    assert request_id != "bad id\r\ninjected"
    assert response.json()["error"]["request_id"] == request_id
    [event] = _events(caplog)
    assert event["request_id"] == request_id
    assert event["result"] == 401
    assert event["error_code"] == "AUTH_EXPIRED"
    assert event["user_id"] is None


def test_cli_audit_logs_dependency_errors_without_sensitive_payload(caplog) -> None:
    caplog.set_level(logging.INFO, logger="dy_api.cli_audit")
    unavailable = AuditStore()
    unavailable.available = False
    client = _client(unavailable)

    response = client.get("/api/v1/cli/stores")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "API_UNAVAILABLE"
    [event] = _events(caplog)
    assert event["user_id"] == "user-1"
    assert event["result"] == 503
    assert event["error_code"] == "API_UNAVAILABLE"


def test_non_cli_paths_keep_existing_error_shape_and_are_not_audited(caplog) -> None:
    caplog.set_level(logging.INFO, logger="dy_api.cli_audit")
    client = TestClient(create_app())

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert "x-request-id" not in response.headers
    assert _events(caplog) == []
