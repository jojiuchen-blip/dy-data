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
        "meta": {"partial": False, "request_id": "req-server"},
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
        "meta": {"partial": False, "request_id": "req-server"},
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
            "request_id": "req-server",
            "generated_at": "2026-07-21T12:00:00+00:00",
            "data_as_of": "2026-07-21T12:00:00+00:00",
            "source": "postgres",
        },
    }


def execute_http_response(
    argv: list[str], payload: dict[str, Any]
) -> tuple[int, str]:
    client = DyDataClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=payload,
                headers={"X-Request-ID": "req-server"},
            )
        )
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
