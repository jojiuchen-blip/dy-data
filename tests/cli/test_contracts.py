from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Any, Callable

import httpx
import pytest

from dydata_cli.client import DyDataClient
from dydata_cli.commands import execute_command
from dydata_cli.credentials import CredentialState
from dydata_cli.parser import parse_args


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
CANONICAL_REQUEST_ID = "req_" + "a" * 32


class FakeCredentialStore:
    def __init__(self) -> None:
        self.state: CredentialState | None = CredentialState(
            access_token="access-secret",
            access_token_expires_at=NOW + timedelta(minutes=10),
            refresh_token="refresh-secret",
        )

    def load(self) -> CredentialState | None:
        return self.state

    def save(self, state: CredentialState) -> None:
        self.state = state

    def clear(self) -> None:
        self.state = None


def auth_status_envelope() -> dict[str, Any]:
    return {
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
            "expires_at": "2026-07-21T12:30:00+00:00",
        },
        "meta": {"partial": False, "request_id": CANONICAL_REQUEST_ID},
    }


def stores_envelope() -> dict[str, Any]:
    return {
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
        "meta": {"partial": False, "request_id": CANONICAL_REQUEST_ID},
    }


def follow_up_envelope() -> dict[str, Any]:
    metrics = {
        "total_count": 4,
        "pending_count": 1,
        "followed_count": 2,
        "other_status_count": 1,
        "action_followed_count": 3,
        "effective_followed_count": 2,
        "system_follow_up_rate": 0.5,
        "action_follow_rate": 0.75,
    }
    return {
        "ok": True,
        "command": "clues.follow-up-stats",
        "schema_version": "1.0",
        "metric_version": "clue-follow-up-v1",
        "scope": {
            "user_id": "user-1",
            "requested_store_ids": ["store-a"],
            "effective_store_ids": ["store-a"],
        },
        "filters": {
            "assigned_date_start": "2026-07-15",
            "assigned_date_end": "2026-07-21",
            "timezone": "Asia/Shanghai",
        },
        "data": {
            "stores": [
                {"store_id": "store-a", "store_name": "Alpha", **metrics}
            ],
            "totals": metrics,
        },
        "meta": {
            "partial": False,
            "request_id": CANONICAL_REQUEST_ID,
            "generated_at": "2026-07-21T12:00:00+00:00",
            "data_as_of": "2026-07-21T12:00:00+00:00",
            "source": "postgres",
        },
    }


def execute_http_response(
    argv: list[str], payload: dict[str, Any]
) -> tuple[int, str]:
    def handler(request: httpx.Request) -> httpx.Response:
        payload["meta"]["request_id"] = request.headers["X-Request-ID"]
        return httpx.Response(
            200,
            json=payload,
            headers={"X-Request-ID": request.headers["X-Request-ID"]},
        )

    client = DyDataClient(
        transport=httpx.MockTransport(handler)
    )
    stream = StringIO()
    exit_code = execute_command(
        parse_args(argv, today=NOW.date()),
        credential_store=FakeCredentialStore(),
        client=client,
        now=lambda: NOW,
        stream=stream,
    )
    return exit_code, stream.getvalue()


def execute_request_id_response(
    argv: list[str],
    payload: dict[str, Any],
    *,
    response_request_id: str | None,
    status_code: int = 200,
) -> tuple[int, str, str]:
    sent_request_id = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent_request_id
        sent_request_id = request.headers["X-Request-ID"]
        response_payload = deepcopy(payload)
        if status_code >= 400:
            error = response_payload["error"]
            error["request_id"] = response_request_id or sent_request_id
        else:
            meta = response_payload["meta"]
            meta["request_id"] = response_request_id or sent_request_id
        return httpx.Response(status_code, json=response_payload)

    client = DyDataClient(
        transport=httpx.MockTransport(handler),
        max_attempts=1,
    )
    stream = StringIO()
    exit_code = execute_command(
        parse_args(argv, today=NOW.date()),
        credential_store=FakeCredentialStore(),
        client=client,
        now=lambda: NOW,
        stream=stream,
    )
    return exit_code, stream.getvalue(), sent_request_id


@pytest.mark.parametrize(
    ("argv", "payload_factory"),
    [
        (["auth", "status", "--json"], auth_status_envelope),
        (["stores", "list", "--json"], stores_envelope),
        (["clues", "follow-up-stats"], follow_up_envelope),
    ],
)
def test_protected_commands_emit_only_exact_validated_success_contract(
    argv: list[str], payload_factory: Callable[[], dict[str, Any]]
) -> None:
    payload = payload_factory()

    exit_code, stdout = execute_http_response(argv, payload)

    assert exit_code == 0
    assert stdout.count("\n") == 1
    assert __import__("json").loads(stdout) == payload


def invalid_success_cases() -> list[tuple[list[str], dict[str, Any], str]]:
    partial = stores_envelope()
    partial["meta"]["partial"] = True
    partial["token"] = "SENSITIVE_PARTIAL"

    wrong_command = auth_status_envelope()
    wrong_command["command"] = "stores.list"
    wrong_command["token"] = "SENSITIVE_COMMAND"

    auth_extra = auth_status_envelope()
    auth_extra["data"]["access_token"] = "SENSITIVE_TOKEN"

    store_extra = stores_envelope()
    store_extra["data"]["stores"][0].update(
        {
            "customer_phone": "SENSITIVE_PHONE",
            "order_id": "SENSITIVE_ORDER",
        }
    )

    stats_extra = follow_up_envelope()
    stats_extra["data"]["stores"][0]["note"] = "SENSITIVE_NOTE"

    stats_type = follow_up_envelope()
    stats_type["data"]["totals"]["total_count"] = True
    stats_type["meta"]["token"] = "SENSITIVE_TYPE"

    stats_count_identity = follow_up_envelope()
    stats_count_identity["data"]["stores"][0]["pending_count"] = 2
    stats_count_identity["data"]["stores"][0]["store_name"] = "SENSITIVE_COUNT_IDENTITY"

    stats_rate_identity = follow_up_envelope()
    stats_rate_identity["data"]["stores"][0]["system_follow_up_rate"] = 0.75
    stats_rate_identity["data"]["stores"][0]["store_name"] = "SENSITIVE_RATE_IDENTITY"

    stats_total_identity = follow_up_envelope()
    stats_total_identity["data"]["totals"]["total_count"] = 5
    stats_total_identity["meta"]["source"] = "SENSITIVE_TOTAL_IDENTITY"

    stats_duplicate_store = follow_up_envelope()
    stats_duplicate_store["data"]["stores"].append(
        deepcopy(stats_duplicate_store["data"]["stores"][0])
    )
    stats_duplicate_store["data"]["stores"][0]["store_name"] = "SENSITIVE_DUPLICATE_STORE"
    stats_duplicate_store["data"]["stores"][1]["store_name"] = "SENSITIVE_DUPLICATE_STORE"

    stats_scope_drift = follow_up_envelope()
    stats_scope_drift["scope"]["effective_store_ids"] = ["store-b"]
    stats_scope_drift["data"]["stores"][0]["store_name"] = "SENSITIVE_SCOPE_DRIFT"

    stores_scope_drift = stores_envelope()
    stores_scope_drift["scope"]["effective_store_ids"] = ["store-a"]
    stores_scope_drift["data"]["stores"][0]["store_name"] = "SENSITIVE_STORE_SCOPE_DRIFT"

    stores_unsorted = stores_envelope()
    stores_unsorted["data"]["stores"].reverse()
    stores_unsorted["data"]["stores"][0]["store_name"] = "SENSITIVE_STORE_ORDER"

    return [
        (["stores", "list", "--json"], partial, "SENSITIVE_PARTIAL"),
        (["auth", "status", "--json"], wrong_command, "SENSITIVE_COMMAND"),
        (["auth", "status", "--json"], auth_extra, "SENSITIVE_TOKEN"),
        (["stores", "list", "--json"], store_extra, "SENSITIVE_PHONE"),
        (["clues", "follow-up-stats"], stats_extra, "SENSITIVE_NOTE"),
        (
            ["clues", "follow-up-stats", "--output", "table"],
            stats_extra,
            "SENSITIVE_NOTE",
        ),
        (["clues", "follow-up-stats"], stats_type, "SENSITIVE_TYPE"),
        (
            ["clues", "follow-up-stats"],
            stats_count_identity,
            "SENSITIVE_COUNT_IDENTITY",
        ),
        (
            ["clues", "follow-up-stats"],
            stats_rate_identity,
            "SENSITIVE_RATE_IDENTITY",
        ),
        (
            ["clues", "follow-up-stats"],
            stats_total_identity,
            "SENSITIVE_TOTAL_IDENTITY",
        ),
        (
            ["clues", "follow-up-stats"],
            stats_duplicate_store,
            "SENSITIVE_DUPLICATE_STORE",
        ),
        (
            ["clues", "follow-up-stats"],
            stats_scope_drift,
            "SENSITIVE_SCOPE_DRIFT",
        ),
        (
            ["stores", "list", "--json"],
            stores_scope_drift,
            "SENSITIVE_STORE_SCOPE_DRIFT",
        ),
        (
            ["stores", "list", "--json"],
            stores_unsorted,
            "SENSITIVE_STORE_ORDER",
        ),
    ]


@pytest.mark.parametrize(("argv", "payload", "marker"), invalid_success_cases())
def test_invalid_success_contract_is_rejected_without_sensitive_output(
    argv: list[str], payload: dict[str, Any], marker: str
) -> None:
    exit_code, stdout = execute_http_response(argv, deepcopy(payload))

    document = __import__("json").loads(stdout)
    assert exit_code == 6
    assert document["error"]["code"] == "SCHEMA_MISMATCH"
    assert marker not in stdout


@pytest.mark.parametrize(
    ("argv", "payload_factory"),
    [
        (["auth", "status", "--json"], auth_status_envelope),
        (["stores", "list", "--json"], stores_envelope),
        (["clues", "follow-up-stats"], follow_up_envelope),
    ],
)
@pytest.mark.parametrize(
    "remote_request_id",
    ["refresh-token-like-secret", "req_" + "b" * 32],
)
def test_success_request_id_must_exactly_echo_the_sent_id(
    argv: list[str],
    payload_factory: Callable[[], dict[str, Any]],
    remote_request_id: str,
) -> None:
    exit_code, stdout, sent_request_id = execute_request_id_response(
        argv,
        payload_factory(),
        response_request_id=remote_request_id,
    )

    document = __import__("json").loads(stdout)
    assert exit_code == 6
    assert document["error"]["code"] == "SCHEMA_MISMATCH"
    assert document["error"]["request_id"] == sent_request_id
    assert remote_request_id not in stdout


@pytest.mark.parametrize(
    ("argv", "payload_factory"),
    [
        (["auth", "status", "--json"], auth_status_envelope),
        (["stores", "list", "--json"], stores_envelope),
        (["clues", "follow-up-stats"], follow_up_envelope),
    ],
)
def test_success_request_id_accepts_the_exact_echo(
    argv: list[str], payload_factory: Callable[[], dict[str, Any]]
) -> None:
    exit_code, stdout, sent_request_id = execute_request_id_response(
        argv,
        payload_factory(),
        response_request_id=None,
    )

    assert exit_code == 0
    assert __import__("json").loads(stdout)["meta"]["request_id"] == sent_request_id


@pytest.mark.parametrize(
    ("code", "retryable", "status_code", "remote_request_id", "expected_exit"),
    [
        ("API_UNAVAILABLE", True, 503, "refresh-token-like-secret", 5),
        ("SCOPE_DENIED", False, 403, "req_" + "b" * 32, 4),
    ],
)
def test_remote_error_request_id_mismatch_uses_the_sent_local_id(
    code: str,
    retryable: bool,
    status_code: int,
    remote_request_id: str,
    expected_exit: int,
) -> None:
    payload = {
        "ok": False,
        "command": "stores.list",
        "schema_version": "1.0",
        "error": {
            "code": code,
            "message": "unsafe remote message",
            "retryable": retryable,
            "request_id": remote_request_id,
        },
    }

    exit_code, stdout, sent_request_id = execute_request_id_response(
        ["stores", "list", "--json"],
        payload,
        response_request_id=remote_request_id,
        status_code=status_code,
    )

    error = __import__("json").loads(stdout)["error"]
    assert exit_code == expected_exit
    assert error == {
        "code": code,
        "message": {
            "API_UNAVAILABLE": "The dydata API is unavailable.",
            "SCOPE_DENIED": "The requested scope is not permitted.",
        }[code],
        "retryable": retryable,
        "request_id": sent_request_id,
    }
    assert remote_request_id not in stdout


def test_remote_error_request_id_accepts_the_exact_echo() -> None:
    payload = {
        "ok": False,
        "command": "stores.list",
        "schema_version": "1.0",
        "error": {
            "code": "SCOPE_DENIED",
            "message": "unsafe remote message",
            "retryable": False,
            "request_id": CANONICAL_REQUEST_ID,
        },
    }

    exit_code, stdout, sent_request_id = execute_request_id_response(
        ["stores", "list", "--json"],
        payload,
        response_request_id=None,
        status_code=403,
    )

    assert exit_code == 4
    assert __import__("json").loads(stdout)["error"]["request_id"] == sent_request_id
