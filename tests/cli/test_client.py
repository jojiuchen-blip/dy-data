from __future__ import annotations

import inspect
from datetime import date

import httpx
import pytest

from dydata_cli.client import CliError, DyDataClient


CANONICAL_REQUEST_ID = "req_" + "a" * 32


def envelope(command: str, data: dict[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "command": command,
        "environment": "test",
        "schema_version": "1.1",
        "data": data,
        "meta": {"request_id": CANONICAL_REQUEST_ID, "partial": False},
    }


def stores_envelope() -> dict[str, object]:
    payload = envelope("stores.list", {"stores": []})
    payload["scope"] = {
        "user_id": "user-1",
        "effective_store_ids": [],
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
        "clues.follow-up-stats",
        {
            "stores": [
                {"store_id": "store-a", "store_name": "Alpha", **metrics},
                {"store_id": "store-b", "store_name": "Beta", **metrics},
            ],
            "totals": metrics,
        },
    )
    payload["metric_version"] = "clue-follow-up-v1"
    payload["scope"] = {
        "user_id": "user-1",
        "requested_store_ids": ["store-a", "store-b"],
        "effective_store_ids": ["store-a", "store-b"],
    }
    payload["filters"] = {
        "assigned_date_start": "2026-07-01",
        "assigned_date_end": "2026-07-07",
        "timezone": "Asia/Shanghai",
    }
    payload["meta"] = {
        "request_id": CANONICAL_REQUEST_ID,
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
        "get_agent_manifest",
        "get_mcp_resource_metadata",
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
        payload = stores_envelope()
        payload["meta"]["request_id"] = request.headers["X-Request-ID"]
        return httpx.Response(
            200,
            json=payload,
            headers={"X-Request-ID": request.headers["X-Request-ID"]},
        )

    monkeypatch.setenv("DYDATA_API_URL", "https://attacker.example/api/v1")
    client = DyDataClient(
        base_url="https://api.example.test/api/v1///",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    result = client.list_stores("access-secret")

    assert result["data"] == {"stores": []}
    request = captured[0]
    assert str(request.url) == "https://api.example.test/api/v1/cli/stores"
    assert request.headers["Authorization"] == "Bearer access-secret"
    assert request.headers["X-DyData-CLI-Version"] == "0.3.0"
    assert request.headers["X-DyData-Command"] == "stores.list"
    assert request.headers["X-DyData-Schema-Version"] == "1.1"
    assert request.headers["X-Request-ID"].startswith("req_")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8000/api/v1",
        "http://localhost:8000/api/v1/",
        "http://[::1]:8000/api/v1",
        "https://api.example.test/api/v1",
        "https://api.example.test:8443/api/v1///",
    ],
)
def test_base_url_allows_https_and_explicit_loopback_http(base_url: str) -> None:
    client = DyDataClient(base_url=base_url, transport=httpx.MockTransport(lambda _: httpx.Response(200)))

    normalized = str(client._http.base_url)

    assert normalized.endswith("/")
    assert not normalized.endswith("//")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.example.test/api/v1",
        "http://0.0.0.0:8000/api/v1",
        "http://127.0.0.2:8000/api/v1",
        "http://127.0.0.1.evil.test:8000/api/v1",
        "http://localhost/api/v1",
        "https://user:password@api.example.test/api/v1",
        "https:///api/v1",
        "ftp://api.example.test/api/v1",
        "api.example.test/api/v1",
        "https://api.example.test/api/v1?token=secret",
        "https://api.example.test/api/v1#fragment",
        "https://api.example.test/api/../v1",
        "https://api.example.test/api%0av1",
        "https://api.example.test/api\\v1",
        "https://api.example.test:0/api/v1",
        "https://api.example.test:65536/api/v1",
    ],
)
def test_base_url_rejects_cleartext_remote_and_ambiguous_urls(
    base_url: str,
) -> None:
    with pytest.raises(CliError) as raised:
        DyDataClient(base_url=base_url)

    assert raised.value.code == "INVALID_ARGUMENT"
    assert base_url not in str(raised.value)


def test_follow_up_stats_sends_dates_and_repeated_store_ids() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = follow_up_envelope()
        payload["meta"]["request_id"] = request.headers["X-Request-ID"]
        return httpx.Response(
            200,
            json=payload,
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
        store_ids=[" store-b ", "store-a", "store-b"],
    )

    request = captured[0]
    assert request.url.path == "/api/v1/clues/store-follow-up-summary"
    assert request.url.params.multi_items() == [
        ("assigned_date_start", "2026-07-01"),
        ("assigned_date_end", "2026-07-07"),
        ("store_id", "store-a"),
        ("store_id", "store-b"),
    ]


def test_follow_up_stats_rejects_response_date_scope_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = follow_up_envelope()
        payload["filters"]["assigned_date_end"] = "2026-07-08"
        payload["meta"]["source"] = "SENSITIVE_WRONG_PERIOD"
        payload["meta"]["request_id"] = request.headers["X-Request-ID"]
        return httpx.Response(200, json=payload)

    client = DyDataClient(
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    with pytest.raises(CliError) as raised:
        client.follow_up_stats(
            "access-secret",
            date_from=date(2026, 7, 1),
            date_to=date(2026, 7, 7),
            store_ids=["store-a", "store-b"],
        )

    assert raised.value.code == "SCHEMA_MISMATCH"
    assert "SENSITIVE_WRONG_PERIOD" not in str(raised.value)


def device_start_payload() -> dict[str, object]:
    return {
        "device_code": "d" * 43,
        "user_code": "ABCD1234",
        "verification_uri": "https://app.example.test/cli/authorize",
        "verification_uri_complete": (
            "https://app.example.test/cli/authorize?user_code=ABCD1234"
        ),
        "expires_in": 600,
        "interval": 3,
    }


def token_payload() -> dict[str, object]:
    return {
        "access_token": f"cli.{'a' * 32}.{'b' * 64}",
        "refresh_token": "r" * 64,
        "token_type": "Bearer",
        "scope": "cli:read",
        "expires_in": 1800,
        "access_token_expires_at": "2026-07-21T12:30:00Z",
    }


def test_device_and_refresh_lifecycle_accepts_only_documented_json() -> None:
    start_payload = device_start_payload()
    refreshed_payload = token_payload()
    responses = iter(
        [
            httpx.Response(200, json=start_payload),
            httpx.Response(202, json={"status": "authorization_pending"}),
            httpx.Response(200, json=refreshed_payload),
            httpx.Response(200, json={"status": "revoked"}),
        ]
    )

    client = DyDataClient(
        base_url="http://localhost:8000/api/v1",
        transport=httpx.MockTransport(lambda _: next(responses)),
        sleep=lambda _: None,
    )

    assert client.start_device_authorization() == start_payload
    assert client.poll_device_token("d" * 43) == {
        "status": "authorization_pending"
    }
    assert client.refresh("r" * 64) == refreshed_payload
    assert client.revoke("r" * 64) is None


@pytest.mark.parametrize(
    ("operation", "status_code", "payload"),
    [
        ("start_device_authorization", 200, {**device_start_payload(), "secret": "SENSITIVE_AUTH_DRIFT"}),
        ("poll_device_token", 202, {"status": "approved", "secret": "SENSITIVE_AUTH_DRIFT"}),
        ("poll_device_token", 200, {**token_payload(), "scope": "admin"}),
        ("refresh", 200, {**token_payload(), "expires_in": 60}),
        ("revoke", 200, {"status": "revoked", "secret": "SENSITIVE_AUTH_DRIFT"}),
    ],
)
def test_auth_success_contract_drift_is_rejected_without_secret_leakage(
    operation: str, status_code: int, payload: dict[str, object]
) -> None:
    client = DyDataClient(
        base_url="http://localhost:8000/api/v1",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status_code, json=payload)
        ),
    )
    call = getattr(client, operation)

    with pytest.raises(CliError) as raised:
        if operation == "start_device_authorization":
            call()
        elif operation == "poll_device_token":
            call("d" * 43)
        else:
            call("r" * 64)

    assert raised.value.code == "SCHEMA_MISMATCH"
    assert "cli.aaaaaaaa" not in str(raised.value)
    assert ("r" * 64) not in repr(raised.value)


def test_auth_token_expiry_must_be_timezone_aware() -> None:
    payload = token_payload()
    payload["access_token_expires_at"] = "2026-07-21T12:30:00"
    client = DyDataClient(
        base_url="http://localhost:8000/api/v1",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(CliError) as raised:
        client.refresh("r" * 64)

    assert raised.value.code == "SCHEMA_MISMATCH"


@pytest.mark.parametrize(
    ("verification_uri", "verification_uri_complete"),
    [
        (
            "http://portal.example.test/auth/cli/authorize",
            "http://portal.example.test/auth/cli/authorize?user_code=ABCD1234",
        ),
        (
            "http://localhost/auth/cli/authorize",
            "http://localhost/auth/cli/authorize?user_code=ABCD1234",
        ),
        (
            "https://user:password@portal.example.test/auth/cli/authorize",
            "https://user:password@portal.example.test/auth/cli/authorize?user_code=ABCD1234",
        ),
        (
            "https://portal.example.test/auth%0acli/authorize",
            "https://portal.example.test/auth%0acli/authorize?user_code=ABCD1234",
        ),
        (
            "https://portal.example.test/auth/../authorize",
            "https://portal.example.test/auth/../authorize?user_code=ABCD1234",
        ),
        (
            "https://portal.example.test/auth/cli/authorize",
            "https://evil.example.test/auth/cli/authorize?user_code=ABCD1234",
        ),
    ],
)
def test_device_verification_urls_reuse_transport_security_policy(
    verification_uri: str, verification_uri_complete: str
) -> None:
    payload = device_start_payload()
    payload["verification_uri"] = verification_uri
    payload["verification_uri_complete"] = verification_uri_complete
    client = DyDataClient(
        base_url="http://localhost:8000/api/v1",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    with pytest.raises(CliError) as raised:
        client.start_device_authorization()

    assert raised.value.code == "SCHEMA_MISMATCH"
    assert verification_uri not in str(raised.value)


@pytest.mark.parametrize(
    "verification_uri",
    [
        "https://portal.example.test/auth/cli/authorize",
        "http://127.0.0.1:5173/auth/cli/authorize",
        "http://localhost:5173/auth/cli/authorize",
        "http://[::1]:5173/auth/cli/authorize",
    ],
)
def test_device_verification_urls_accept_https_and_explicit_loopback(
    verification_uri: str,
) -> None:
    payload = device_start_payload()
    payload["verification_uri"] = verification_uri
    payload["verification_uri_complete"] = (
        f"{verification_uri}?user_code=ABCD1234"
    )
    client = DyDataClient(
        base_url="http://localhost:8000/api/v1",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )

    assert client.start_device_authorization()["verification_uri"] == verification_uri


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
    ("operation", "argument"),
    [
        ("start_device_authorization", None),
        ("poll_device_token", "device-secret"),
        ("refresh", "refresh-secret"),
        ("revoke", "refresh-secret"),
    ],
)
def test_authentication_posts_are_single_submission_on_network_failure(
    operation: str, argument: str | None
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("connection dropped", request=request)

    client = DyDataClient(
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    call = getattr(client, operation)

    with pytest.raises(CliError) as raised:
        call() if argument is None else call(argument)

    assert raised.value.code == "API_UNAVAILABLE"
    assert attempts == 1


@pytest.mark.parametrize("status_code", [429, 503])
def test_refresh_post_does_not_retry_retryable_http_statuses(
    status_code: int,
) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code, json={})

    client = DyDataClient(
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    with pytest.raises(CliError):
        client.refresh("refresh-secret")

    assert attempts == 1


@pytest.mark.parametrize(
    ("code", "remote_retryable", "expected_retryable"),
    [
        ("API_UNAVAILABLE", True, True),
        ("SCOPE_DENIED", False, False),
        ("API_UNAVAILABLE", False, True),
        ("SCOPE_DENIED", True, False),
    ],
)
def test_remote_error_preserves_safe_request_id_and_retryability(
    code: str, remote_retryable: bool, expected_retryable: bool
) -> None:
    echoed_request_id = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal echoed_request_id
        echoed_request_id = request.headers["X-Request-ID"]
        return httpx.Response(
            503 if code == "API_UNAVAILABLE" else 403,
            json={
                "ok": False,
                "command": "stores.list",
                "schema_version": "1.0",
                "error": {
                    "code": code,
                    "message": "unsafe access-secret",
                    "retryable": remote_retryable,
                    "request_id": echoed_request_id,
                },
            },
        )

    client = DyDataClient(
        transport=httpx.MockTransport(handler),
        max_attempts=1,
    )

    with pytest.raises(CliError) as raised:
        client.list_stores("access-secret")

    assert raised.value.code == code
    assert raised.value.retryable is expected_retryable
    assert raised.value.request_id == echoed_request_id
    assert "access-secret" not in str(raised.value)


def test_retries_use_one_stable_logical_request_id_and_require_its_echo() -> None:
    request_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_id = request.headers["X-Request-ID"]
        request_ids.append(request_id)
        if len(request_ids) == 1:
            return httpx.Response(503, json={})
        payload = stores_envelope()
        payload["meta"]["request_id"] = request_id
        return httpx.Response(200, json=payload)

    client = DyDataClient(
        transport=httpx.MockTransport(handler),
        max_attempts=2,
        sleep=lambda _: None,
    )

    result = client.list_stores("access-secret")

    assert result["meta"]["request_id"] == request_ids[0]
    assert request_ids == [request_ids[0], request_ids[0]]


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": True, "schema_version": "2.0", "data": {}},
        {"ok": False, "schema_version": "1.1", "data": {}},
        {"ok": True, "data": {}},
    ],
)
def test_success_envelope_requires_schema_1_1_and_ok_true(
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
