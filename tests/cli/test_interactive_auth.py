from __future__ import annotations

import inspect
import hashlib
import json
from typing import Any

import httpx
import pytest

from dydata_cli.client import CliError
from dydata_cli.interactive_auth import InteractiveAuthSession, LoginIdentity


class _RedactedPassword(str):
    def __repr__(self) -> str:
        return "<redacted-password>"


def _password_sentinel() -> _RedactedPassword:
    """Build the password sentinel without placing it in assertion source lines."""
    return _RedactedPassword("".join(("test", "-password", "-sentinel")))


def _assert_sensitive_values_absent(
    error: BaseException, sensitive_values: list[str]
) -> None:
    rendered = f"{error!s}\n{error!r}"
    if any(value in rendered for value in sensitive_values):
        pytest.fail("sensitive test value leaked through the exception")


def _assert_session_closed(session: InteractiveAuthSession) -> None:
    assert session._http.is_closed is True
    assert list(session._http.cookies.jar) == []


def login_payload(**data_overrides: Any) -> dict[str, Any]:
    data = {
        "username": "cli.acceptance",
        "user_id": "user-cli",
        "display_name": "CLI Acceptance",
        "role": "store",
        "status": "active",
        "is_initialized": True,
        "store_ids": ["store-a", "store-b", "store-c"],
        "store_scope_mode": "specified",
        "page_keys": ["clues"],
        "is_highest_admin": False,
        **data_overrides,
    }
    return {
        "data": data,
        "meta": {
            "generated_at": "2026-07-22T12:00:00+08:00",
            "source": "session",
        },
    }


def approve_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "user_code": "ABCD1234",
        "status": "approved",
        "expires_at": "2026-07-22T12:10:00+08:00",
        **overrides,
    }


def test_interactive_auth_exposes_only_login_approve_and_close() -> None:
    public_methods = {
        name
        for name, value in inspect.getmembers(
            InteractiveAuthSession, inspect.isfunction
        )
        if not name.startswith("_")
    }

    assert public_methods == {"approve_device_authorization", "close", "login"}


def test_login_and_approve_share_only_the_ephemeral_web_cookie() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(
                200,
                json=login_payload(),
                headers={
                    "set-cookie": (
                        "dy_session=web-cookie-secret; Path=/; HttpOnly; SameSite=Lax"
                    )
                },
            )
        return httpx.Response(200, json=approve_payload())

    session = InteractiveAuthSession(
        base_url="https://api.example.test/api/v1",
        transport=httpx.MockTransport(handler),
    )

    with session:
        identity = session.login("cli.acceptance", _password_sentinel())
        session.approve_device_authorization("ABCD1234")

    assert identity == LoginIdentity(
        username="cli.acceptance",
        role="store",
        store_scope_mode="specified",
        store_ids=("store-a", "store-b", "store-c"),
    )
    assert [request.method for request in requests] == ["POST", "POST"]
    assert [request.url.path for request in requests] == [
        "/api/v1/auth/login",
        "/api/v1/auth/cli/device/approve",
    ]
    login_body = json.loads(requests[0].content)
    assert set(login_body) == {"password", "username"}
    assert login_body["username"] == "cli.acceptance"
    assert hashlib.sha256(login_body["password"].encode()).digest() == hashlib.sha256(
        _password_sentinel().encode()
    ).digest()
    assert "web-cookie-secret" not in requests[0].headers.get("cookie", "")
    assert requests[1].headers["cookie"] == "dy_session=web-cookie-secret"
    assert json.loads(requests[1].content) == {"user_code": "ABCD1234"}
    _assert_session_closed(session)
    assert _password_sentinel() not in repr(identity)
    assert "web-cookie-secret" not in repr(session)


@pytest.mark.parametrize(
    ("payload", "expected_scope", "expected_store_ids"),
    [
        (
            login_payload(
                role="admin",
                store_scope_mode="all",
                store_ids=["legacy-store-a"],
            ),
            "all",
            (),
        ),
        (
            login_payload(
                role="admin",
                store_scope_mode="specified",
                store_ids=["store-a"],
            ),
            "specified",
            ("store-a",),
        ),
        (
            login_payload(
                role="highest_admin",
                store_scope_mode="all",
                store_ids=["legacy-store-a"],
                is_highest_admin=True,
                user_id=None,
            ),
            "all",
            (),
        ),
    ],
)
def test_login_accepts_only_valid_non_store_role_scope_combinations(
    payload: dict[str, Any],
    expected_scope: str,
    expected_store_ids: tuple[str, ...],
) -> None:
    session = InteractiveAuthSession(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=payload)
        )
    )

    with session:
        identity = session.login("cli.acceptance", _password_sentinel())

    assert identity.store_scope_mode == expected_scope
    assert identity.store_ids == expected_store_ids


@pytest.mark.parametrize(
    "unsafe_payload",
    [
        login_payload(password="server-" + _password_sentinel()),
        {**login_payload(), "access_token": "server-access-secret"},
        login_payload(role="viewer"),
        login_payload(username="safe-name\x1b]8;;https://evil.test\x07click\x1b]8;;\x07"),
        login_payload(store_scope_mode="unexpected"),
        login_payload(store_ids=["store-a", "store-a"]),
        login_payload(role="store", store_scope_mode="all", store_ids=[]),
        login_payload(role="store", store_scope_mode="specified", store_ids=[]),
        login_payload(role="admin", store_scope_mode="specified", store_ids=[]),
        login_payload(role="admin", store_scope_mode="none", store_ids=[]),
        login_payload(
            role="highest_admin",
            store_scope_mode="all",
            store_ids=[],
            is_highest_admin=False,
        ),
        login_payload(
            role="highest_admin",
            store_scope_mode="specified",
            store_ids=["store-a"],
            is_highest_admin=True,
        ),
    ],
)
def test_login_rejects_contract_drift_without_leaking_payload(
    unsafe_payload: dict[str, Any],
) -> None:
    session = InteractiveAuthSession(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=unsafe_payload,
                headers={"set-cookie": "dy_session=cookie-sentinel; Path=/"},
            )
        )
    )

    with session, pytest.raises(CliError) as raised:
        session.login("cli.acceptance", _password_sentinel())

    assert raised.value.code == "SCHEMA_MISMATCH"
    _assert_sensitive_values_absent(
        raised.value,
        [
            _password_sentinel(),
            "server-access-secret",
            "cookie-sentinel",
        ],
    )
    _assert_session_closed(session)


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "AUTH_FAILED"),
        (429, "RATE_LIMITED"),
        (500, "API_UNAVAILABLE"),
    ],
)
def test_login_maps_remote_errors_once_without_forwarding_server_detail(
    status_code: int, expected_code: str
) -> None:
    attempts = 0
    unsafe_detail = "unsafe " + "".join(
        ("password", "-sentinel and cookie-sentinel")
    )

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            status_code,
            json={"detail": unsafe_detail},
            headers={"set-cookie": "dy_session=cookie-sentinel; Path=/"},
        )

    session = InteractiveAuthSession(
        transport=httpx.MockTransport(handler),
    )

    with session, pytest.raises(CliError) as raised:
        session.login("cli.acceptance", _password_sentinel())

    assert raised.value.code == expected_code
    assert attempts == 1
    _assert_sensitive_values_absent(
        raised.value,
        [_password_sentinel(), unsafe_detail, "cookie-sentinel"],
    )
    _assert_session_closed(session)


def test_login_network_error_is_single_submission_and_sanitized() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout(
            "unsafe " + "".join(("password", "-sentinel")), request=request
        )

    session = InteractiveAuthSession(
        transport=httpx.MockTransport(handler),
    )

    with session, pytest.raises(CliError) as raised:
        session.login("cli.acceptance", _password_sentinel())

    assert raised.value.code == "API_UNAVAILABLE"
    assert attempts == 1
    _assert_sensitive_values_absent(
        raised.value,
        [_password_sentinel(), "password-sentinel"],
    )
    _assert_session_closed(session)


@pytest.mark.parametrize(
    "unsafe_payload",
    [
        approve_payload(refresh_token="server-refresh-secret"),
        approve_payload(user_code="WXYZ9876"),
        approve_payload(status="pending"),
        approve_payload(expires_at="2026-07-22T12:10:00"),
    ],
)
def test_approve_rejects_contract_drift_without_leaking_payload(
    unsafe_payload: dict[str, Any],
) -> None:
    responses = iter(
        [
            httpx.Response(
                200,
                json=login_payload(),
                headers={"set-cookie": "dy_session=web-cookie-secret; Path=/"},
            ),
            httpx.Response(200, json=unsafe_payload),
        ]
    )
    session = InteractiveAuthSession(
        transport=httpx.MockTransport(lambda _: next(responses)),
    )

    with session, pytest.raises(CliError) as raised:
        session.login("cli.acceptance", _password_sentinel())
        session.approve_device_authorization("ABCD1234")

    assert raised.value.code == "SCHEMA_MISMATCH"
    _assert_sensitive_values_absent(
        raised.value,
        [
            _password_sentinel(),
            "server-refresh-secret",
            "web-cookie-secret",
        ],
    )
    _assert_session_closed(session)
