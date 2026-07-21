from __future__ import annotations

import inspect
from datetime import date

import httpx
import pytest

from dydata_cli.client import CliError, DyDataClient


def envelope(command: str, data: dict[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "command": command,
        "schema_version": "1.0",
        "data": data,
        "meta": {"request_id": "req-server", "partial": False},
    }


def stores_envelope() -> dict[str, object]:
    payload = envelope("stores.list", {"stores": []})
    payload["scope"] = {
        "user_id": "user-1",
        "effective_store_ids": ["store-a", "store-b"],
    }
    return payload


def follow_up_envelope() -> dict[str, object]:
    metrics = {
        "total_count": 0,
        "pending_count": 0,
        "followed_count": 0,
        "other_status_count": 0,
        "action_followed_count": 0,
        "effective_followed_count": 0,
        "system_follow_up_rate": 0.0,
        "action_follow_rate": 0.0,
    }
    payload = envelope(
        "clues.follow-up-stats", {"stores": [], "totals": metrics}
    )
    payload["metric_version"] = "clue-follow-up-v1"
    payload["scope"] = {
        "user_id": "user-1",
        "requested_store_ids": ["store-b", "store-a"],
        "effective_store_ids": ["store-b", "store-a"],
    }
    payload["filters"] = {
        "assigned_date_start": "2026-07-01",
        "assigned_date_end": "2026-07-07",
        "timezone": "Asia/Shanghai",
    }
    payload["meta"] = {
        "request_id": "req-server",
        "partial": False,
        "generated_at": "2026-07-21T12:00:00Z",
        "data_as_of": "2026-07-21T12:00:00Z",
        "source": "postgres",
    }
    return payload


def test_client_exposes_only_approved_operations() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(DyDataClient, inspect.isfunction)
        if not name.startswith("_")
    }

    assert public_methods == {
        "auth_status",
        "follow_up_stats",
        "list_stores",
        "poll_device_token",
        "refresh",
        "revoke",
        "start_device_authorization",
    }


def test_protected_request_uses_normalized_base_url_and_audit_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=stores_envelope(),
            headers={"X-Request-ID": "req-server"},
        )

    monkeypatch.setenv("DYDATA_API_URL", "https://api.example.test/api/v1///")
    client = DyDataClient(transport=httpx.MockTransport(handler), sleep=lambda _: None)

    result = client.list_stores("access-secret")

    assert result["data"] == {"stores": []}
    request = captured[0]
    assert str(request.url) == "https://api.example.test/api/v1/cli/stores"
    assert request.headers["Authorization"] == "Bearer access-secret"
    assert request.headers["X-DyData-CLI-Version"] == "0.1.0"
    assert request.headers["X-DyData-Command"] == "stores.list"
    assert request.headers["X-DyData-Schema-Version"] == "1.0"
    assert request.headers["X-Request-ID"].startswith("req_")


def test_follow_up_stats_sends_dates_and_repeated_store_ids() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=follow_up_envelope(),
        )

    client = DyDataClient(
        base_url="http://localhost:8000/api/v1",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    client.follow_up_stats(
        "access-secret",
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 7),
        store_ids=["store-b", "store-a"],
    )

    request = captured[0]
    assert request.url.path == "/api/v1/clues/store-follow-up-summary"
    assert request.url.params.multi_items() == [
        ("assigned_date_start", "2026-07-01"),
        ("assigned_date_end", "2026-07-07"),
        ("store_id", "store-b"),
        ("store_id", "store-a"),
    ]


def test_device_and_refresh_lifecycle_accept_bare_json_and_empty_revoke() -> None:
    responses = iter(
        [
            httpx.Response(200, json={"device_code": "device-secret", "interval": 3}),
            httpx.Response(202, json={"status": "authorization_pending"}),
            httpx.Response(
                200,
                json={
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "access_token_expires_at": "2026-07-21T12:30:00Z",
                },
            ),
            httpx.Response(204),
        ]
    )

    client = DyDataClient(
        base_url="http://localhost:8000/api/v1",
        transport=httpx.MockTransport(lambda _: next(responses)),
        sleep=lambda _: None,
    )

    assert client.start_device_authorization()["device_code"] == "device-secret"
    assert client.poll_device_token("device-secret") == {
        "status": "authorization_pending"
    }
    assert client.refresh("refresh-secret")["access_token"] == "access-secret"
    assert client.revoke("refresh-secret") is None


@pytest.mark.parametrize(
    ("status_code", "body", "expected_code", "expected_attempts"),
    [
        (401, {}, "AUTH_EXPIRED", 1),
        (403, {}, "SCOPE_DENIED", 1),
        (422, {}, "INVALID_ARGUMENT", 1),
        (429, {}, "RATE_LIMITED", 3),
        (500, {}, "API_UNAVAILABLE", 3),
    ],
)
def test_http_errors_map_to_stable_codes_and_retry_only_retryable_statuses(
    status_code: int,
    body: dict[str, object],
    expected_code: str,
    expected_attempts: int,
) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, json=body)

    client = DyDataClient(
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    with pytest.raises(CliError) as raised:
        client.auth_status("access-secret")

    assert raised.value.code == expected_code
    assert attempts == expected_attempts
    assert "access-secret" not in str(raised.value)
    assert "access-secret" not in repr(raised.value)


def test_network_timeouts_are_retried_then_mapped_without_token_leakage() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("unsafe access-secret", request=request)

    client = DyDataClient(
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    with pytest.raises(CliError) as raised:
        client.auth_status("access-secret")

    assert raised.value.code == "API_UNAVAILABLE"
    assert attempts == 3
    assert "access-secret" not in str(raised.value)
    assert "unsafe" not in str(raised.value)


@pytest.mark.parametrize(
    ("code", "retryable"),
    [("API_UNAVAILABLE", True), ("SCOPE_DENIED", False)],
)
def test_remote_error_preserves_safe_request_id_and_retryability(
    code: str, retryable: bool
) -> None:
    response = httpx.Response(
        503 if retryable else 403,
        json={
            "ok": False,
            "command": "stores.list",
            "schema_version": "1.0",
            "error": {
                "code": code,
                "message": "unsafe access-secret",
                "retryable": retryable,
                "request_id": "req-remote",
            },
        },
    )
    client = DyDataClient(
        transport=httpx.MockTransport(lambda _: response),
        max_attempts=1,
    )

    with pytest.raises(CliError) as raised:
        client.list_stores("access-secret")

    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert raised.value.request_id == "req-remote"
    assert "access-secret" not in str(raised.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": True, "schema_version": "2.0", "data": {}},
        {"ok": False, "schema_version": "1.0", "data": {}},
        {"ok": True, "data": {}},
    ],
)
def test_success_envelope_requires_schema_1_0_and_ok_true(
    payload: dict[str, object],
) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, json=payload)

    client = DyDataClient(transport=httpx.MockTransport(handler))

    with pytest.raises(CliError) as raised:
        client.list_stores("access-secret")

    assert raised.value.code == "SCHEMA_MISMATCH"
    assert attempts == 1
