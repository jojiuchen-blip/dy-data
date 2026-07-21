from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.auth import AuthContext  # noqa: E402
from dy_api.cli_auth import create_cli_access_token, get_current_cli_user  # noqa: E402
from dy_api.main import create_app  # noqa: E402
from dy_api.routes._data import get_data_store  # noqa: E402


class FakeStore:
    available = True

    def __init__(self) -> None:
        self.list_calls: list[tuple[str, ...] | None] = []
        self.summary_calls: list[dict[str, Any]] = []
        self.stores = [
            {"store_id": "store-b", "store_name": "Beta"},
            {"store_id": "store-empty", "store_name": "Empty"},
            {"store_id": "store-a", "store_name": "Alpha"},
        ]
        self.rows = {
            "store-a": {
                "store_id": "store-a",
                "store_name": "Alpha",
                "total_count": 4,
                "pending_count": 1,
                "followed_count": 2,
                "other_status_count": 1,
                "action_followed_count": 3,
                "effective_followed_count": 2,
                "system_follow_up_rate": 0.5,
                "action_follow_rate": 0.75,
            },
            "store-b": {
                "store_id": "store-b",
                "store_name": "Beta",
                "total_count": 2,
                "pending_count": 0,
                "followed_count": 1,
                "other_status_count": 1,
                "action_followed_count": 2,
                "effective_followed_count": 1,
                "system_follow_up_rate": 0.5,
                "action_follow_rate": 1.0,
            },
            "store-empty": {
                "store_id": "store-empty",
                "store_name": "Empty",
                "total_count": 0,
                "pending_count": 0,
                "followed_count": 0,
                "other_status_count": 0,
                "action_followed_count": 0,
                "effective_followed_count": 0,
                "system_follow_up_rate": 0,
                "action_follow_rate": 0,
            },
        }

    def list_stores(
        self, scope_store_ids: tuple[str, ...] | None = None
    ) -> list[dict[str, str]]:
        self.list_calls.append(scope_store_ids)
        allowed = None if scope_store_ids is None else set(scope_store_ids)
        return [
            row.copy()
            for row in self.stores
            if allowed is None or row["store_id"] in allowed
        ]

    def clue_store_follow_up_summary(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.summary_calls.append(kwargs)
        return [self.rows[store_id].copy() for store_id in kwargs["store_ids"]]


def _auth(*, role: str = "store", store_ids: tuple[str, ...] = ("store-a",)):
    return AuthContext(
        user_id="user-1",
        username="operator",
        display_name="Operator",
        role=role,
        store_ids=store_ids,
        auth_type="user",
    )


def _client(auth: AuthContext, store: FakeStore | None = None) -> tuple[TestClient, FakeStore]:
    app = create_app()
    fake_store = store or FakeStore()
    app.dependency_overrides[get_current_cli_user] = lambda: auth
    app.dependency_overrides[get_data_store] = lambda: fake_store
    return TestClient(app), fake_store


def _assert_error(response, *, status_code: int, command: str, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"ok", "command", "schema_version", "error"}
    assert body["ok"] is False
    assert body["command"] == command
    assert body["schema_version"] == "1.0"
    assert body["error"]["code"] == code
    assert body["error"]["retryable"] is False
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    assert "detail" not in body


def test_cli_auth_status_and_store_list_have_stable_read_only_envelopes() -> None:
    client, store = _client(_auth(store_ids=("store-b", "store-a")))

    auth_status = client.get("/api/v1/cli/auth/status")
    stores = client.get("/api/v1/cli/stores")

    assert auth_status.status_code == 200
    assert auth_status.json() == {
        "ok": True,
        "command": "auth.status",
        "schema_version": "1.0",
        "data": {
            "authenticated": True,
            "user_id": "user-1",
            "username": "operator",
            "display_name": "Operator",
            "role": "store",
            "auth_type": "user",
            "store_ids": ["store-a", "store-b"],
        },
        "meta": {
            "partial": False,
            "request_id": auth_status.headers["x-request-id"],
        },
    }
    assert stores.status_code == 200
    assert stores.json() == {
        "ok": True,
        "command": "stores.list",
        "schema_version": "1.0",
        "scope": {
            "user_id": "user-1",
            "effective_store_ids": ["store-a", "store-b"],
        },
        "data": {
            "stores": [
                {"store_id": "store-a", "store_name": "Alpha"},
                {"store_id": "store-b", "store_name": "Beta"},
            ]
        },
        "meta": {
            "partial": False,
            "request_id": stores.headers["x-request-id"],
        },
    }
    assert store.list_calls == [("store-a", "store-b")]


def test_global_store_list_resolves_all_current_stores() -> None:
    client, store = _client(_auth(role="viewer", store_ids=()))

    response = client.get("/api/v1/cli/stores")

    assert response.status_code == 200
    assert [row["store_id"] for row in response.json()["data"]["stores"]] == [
        "store-a",
        "store-b",
        "store-empty",
    ]
    assert store.list_calls == [None]


def test_follow_up_summary_uses_authorized_subset_and_stable_metric_contract() -> None:
    client, store = _client(
        _auth(store_ids=("store-a", "store-b", "store-empty"))
    )

    response = client.get(
        "/api/v1/clues/store-follow-up-summary",
        params=[
            ("assigned_date_start", "2026-07-01"),
            ("assigned_date_end", "2026-07-07"),
            ("store_id", "store-empty"),
            ("store_id", "store-a"),
            ("store_id", "store-a"),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["command"] == "clues.follow-up-stats"
    assert body["schema_version"] == "1.0"
    assert body["metric_version"] == "clue-follow-up-v1"
    assert body["scope"] == {
        "user_id": "user-1",
        "requested_store_ids": ["store-a", "store-empty"],
        "effective_store_ids": ["store-a", "store-empty"],
    }
    assert body["filters"] == {
        "assigned_date_start": "2026-07-01",
        "assigned_date_end": "2026-07-07",
        "timezone": "Asia/Shanghai",
    }
    assert [row["store_id"] for row in body["data"]["stores"]] == [
        "store-a",
        "store-empty",
    ]
    assert body["data"]["stores"][1]["total_count"] == 0
    assert body["data"]["totals"] == {
        "total_count": 4,
        "pending_count": 1,
        "followed_count": 2,
        "other_status_count": 1,
        "action_followed_count": 3,
        "effective_followed_count": 2,
        "system_follow_up_rate": 0.5,
        "action_follow_rate": 0.75,
    }
    assert body["meta"]["partial"] is False
    assert body["meta"]["source"] == "postgres"
    assert body["meta"]["request_id"] == response.headers["x-request-id"]
    assert store.summary_calls == [
        {
            "store_ids": ("store-a", "store-empty"),
            "assigned_date_start": "2026-07-01",
            "assigned_date_end": "2026-07-07",
        }
    ]


def test_follow_up_summary_defaults_to_inclusive_recent_seven_beijing_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = _client(_auth(store_ids=("store-a",)))
    monkeypatch.setattr("dy_api.routes.cli.beijing_today", lambda: date(2026, 7, 21))

    response = client.get("/api/v1/clues/store-follow-up-summary")

    assert response.status_code == 200
    assert response.json()["filters"] == {
        "assigned_date_start": "2026-07-15",
        "assigned_date_end": "2026-07-21",
        "timezone": "Asia/Shanghai",
    }
    assert store.summary_calls[0]["assigned_date_start"] == "2026-07-15"
    assert store.summary_calls[0]["assigned_date_end"] == "2026-07-21"


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"assigned_date_start": "2026-07-01"}, "INVALID_ARGUMENT"),
        (
            {
                "assigned_date_start": "2026-07-08",
                "assigned_date_end": "2026-07-01",
            },
            "INVALID_ARGUMENT",
        ),
        (
            {
                "assigned_date_start": "2025-07-01",
                "assigned_date_end": "2026-07-02",
            },
            "INVALID_ARGUMENT",
        ),
        (
            {
                "assigned_date_start": "not-a-date",
                "assigned_date_end": "2026-07-01",
            },
            "INVALID_ARGUMENT",
        ),
    ],
)
def test_follow_up_summary_rejects_invalid_date_ranges(params, code) -> None:
    client, store = _client(_auth(store_ids=("store-a",)))

    response = client.get("/api/v1/clues/store-follow-up-summary", params=params)

    _assert_error(
        response,
        status_code=422,
        command="clues.follow-up-stats",
        code=code,
    )
    assert store.summary_calls == []


def test_follow_up_summary_rejects_entire_request_when_any_store_is_unauthorized() -> None:
    client, store = _client(_auth(store_ids=("store-a", "store-b")))

    response = client.get(
        "/api/v1/clues/store-follow-up-summary",
        params=[("store_id", "store-a"), ("store_id", "outside")],
    )

    _assert_error(
        response,
        status_code=403,
        command="clues.follow-up-stats",
        code="SCOPE_DENIED",
    )
    assert store.summary_calls == []


def test_cli_auth_errors_use_top_level_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    client = TestClient(create_app())

    missing = client.get("/api/v1/cli/auth/status")
    expired_auth = AuthContext(
        user_id=None,
        username="system-admin",
        display_name="system-admin",
        role="admin",
        store_ids=(),
        auth_type="env_admin",
    )
    expired_token, _ = create_cli_access_token(
        expired_auth,
        now=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    expired = client.get(
        "/api/v1/cli/auth/status",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    _assert_error(missing, status_code=401, command="auth.status", code="AUTH_REQUIRED")
    _assert_error(expired, status_code=401, command="auth.status", code="AUTH_EXPIRED")


def test_cli_auth_status_reports_access_expiration_without_exposing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    auth = AuthContext(
        user_id=None,
        username="system-admin",
        display_name="system-admin",
        role="admin",
        store_ids=(),
        auth_type="env_admin",
    )
    token, expires_at = create_cli_access_token(auth)

    response = TestClient(create_app()).get(
        "/api/v1/cli/auth/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    signed_expiration = datetime.fromtimestamp(
        int(expires_at.timestamp()), timezone.utc
    ).isoformat()
    assert response.json()["data"]["expires_at"] == signed_expiration
    assert "token" not in response.text.lower()


def test_real_cli_access_token_cannot_call_existing_business_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    auth = AuthContext(
        user_id=None,
        username="system-admin",
        display_name="system-admin",
        role="admin",
        store_ids=(),
        auth_type="env_admin",
    )
    token, _ = create_cli_access_token(auth)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/clues/orders/order-1/follow-up",
        headers={"Authorization": f"Bearer {token}"},
        json={"follow_up_result": "lost"},
    )

    assert response.status_code == 401


def test_openapi_exposes_no_cli_business_writes_and_summary_has_no_detail_fields() -> None:
    client, _ = _client(_auth(role="viewer", store_ids=()))

    paths = client.get("/openapi.json").json()["paths"]
    cli_business_paths = {
        path: operations
        for path, operations in paths.items()
        if path.startswith("/api/v1/cli/")
        or path == "/api/v1/clues/store-follow-up-summary"
    }
    assert cli_business_paths
    assert all(
        not {"post", "put", "patch", "delete"}.intersection(operations)
        for operations in cli_business_paths.values()
    )

    summary = client.get("/api/v1/clues/store-follow-up-summary").json()

    def all_keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(all_keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(all_keys(item) for item in value))
        return set()

    assert not {"phone", "name", "order", "note", "token"}.intersection(
        all_keys(summary)
    )
