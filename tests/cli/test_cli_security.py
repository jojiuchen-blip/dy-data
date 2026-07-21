from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from io import StringIO

import httpx
import pytest

from dydata_cli import commands
from dydata_cli.client import CliError, DyDataClient
from dydata_cli.commands import execute_command
from dydata_cli.credentials import CredentialState, CredentialStore
from dydata_cli.main import main
from dydata_cli.parser import parse_args


class FakeKeyring:
    def __init__(self, raw_value: str | None = None) -> None:
        self.raw_value = raw_value

    def get_password(self, service: str, account: str) -> str | None:
        return self.raw_value

    def set_password(self, service: str, account: str, value: str) -> None:
        self.raw_value = value

    def delete_password(self, service: str, account: str) -> None:
        self.raw_value = None


class FakeStore:
    def __init__(self, state: CredentialState | None) -> None:
        self.state = state

    def load(self) -> CredentialState | None:
        return self.state

    def save(self, state: CredentialState) -> None:
        self.state = state

    def clear(self) -> None:
        self.state = None


def test_credential_store_rejects_empty_or_non_string_secrets() -> None:
    raw_value = json.dumps(
        {
            "access_token": "",
            "access_token_expires_at": "2026-07-21T12:30:00+00:00",
            "refresh_token": ["refresh-secret"],
        }
    )
    keyring = FakeKeyring(raw_value)

    assert CredentialStore(keyring_backend=keyring).load() is None
    assert keyring.raw_value is None


def test_credential_store_public_surface_is_only_load_save_and_clear() -> None:
    methods = {
        name
        for name, value in inspect.getmembers(CredentialStore, inspect.isfunction)
        if not name.startswith("_")
    }

    assert methods == {"load", "save", "clear"}


@pytest.mark.parametrize("argv", [["commands", "--json"], ["version", "--json"]])
def test_offline_commands_never_construct_keyring_or_http_dependencies(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_dependency() -> None:
        raise AssertionError("offline command touched an online dependency")

    monkeypatch.setattr(commands, "CredentialStore", fail_dependency)
    monkeypatch.setattr(commands, "DyDataClient", fail_dependency)

    assert main(argv) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["ok"] is True
    assert captured.err == ""


def test_auth_required_is_one_json_document_with_empty_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class NoNetworkClient:
        pass

    assert main(
        ["auth", "status", "--json"],
        credential_store=FakeStore(None),
        client=NoNetworkClient(),  # type: ignore[arg-type]
    ) == 3
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"]["code"] == "AUTH_REQUIRED"
    assert captured.out.count("\n") == 1
    assert captured.err == ""


def test_auth_status_rejects_any_unexpected_token_fields() -> None:
    state = CredentialState(
        access_token="access-secret",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        refresh_token="refresh-secret",
    )

    class UnsafeStatusClient:
        def auth_status(self, access_token: str) -> dict[str, object]:
            return {
                "ok": True,
                "command": "auth.status",
                "schema_version": "1.0",
                "access_token": access_token,
                "data": {
                    "authenticated": True,
                    "username": "keith",
                    "access_token": access_token,
                    "refresh_token": "server-refresh-secret",
                },
                "meta": {
                    "request_id": "req-safe",
                    "partial": False,
                    "refresh_token": "meta-refresh-secret",
                },
            }

    stream = StringIO()
    exit_code = execute_command(
        parse_args(["auth", "status", "--json"]),
        credential_store=FakeStore(state),
        client=UnsafeStatusClient(),  # type: ignore[arg-type]
        stream=stream,
    )

    assert exit_code == 6
    payload = json.loads(stream.getvalue())
    assert payload["error"]["code"] == "SCHEMA_MISMATCH"
    assert "secret" not in stream.getvalue()


def test_server_error_payload_and_transport_exception_cannot_leak_tokens() -> None:
    bodies = iter(
        [
            httpx.Response(
                403,
                json={
                    "ok": False,
                    "schema_version": "1.0",
                    "error": {
                        "code": "SCOPE_DENIED",
                        "message": "unsafe access-secret",
                        "request_id": "req-safe",
                    },
                },
            )
        ]
    )
    client = DyDataClient(
        transport=httpx.MockTransport(lambda _: next(bodies)),
        sleep=lambda _: None,
    )

    with pytest.raises(CliError) as raised:
        client.list_stores("access-secret")

    assert raised.value.code == "SCOPE_DENIED"
    assert "access-secret" not in str(raised.value)
    assert "unsafe" not in repr(raised.value)


def test_remote_error_contract_survives_into_main_json_without_server_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = CredentialState(
        access_token="access-secret",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        refresh_token="refresh-secret",
    )

    class FailingClient:
        def list_stores(self, access_token: str) -> dict[str, object]:
            assert access_token == "access-secret"
            raise CliError(
                "API_UNAVAILABLE", request_id="req-remote", retryable=True
            )

    assert main(
        ["stores", "list", "--json"],
        credential_store=FakeStore(state),
        client=FailingClient(),  # type: ignore[arg-type]
    ) == 5
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"] == {
        "code": "API_UNAVAILABLE",
        "message": "The dydata API is unavailable.",
        "retryable": True,
        "request_id": "req-remote",
    }
    assert "secret" not in captured.out


def test_token_cannot_be_supplied_as_a_cli_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["stores", "list", "--json", "--token", "access-secret"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(captured.out)["error"]["code"] == "INVALID_ARGUMENT"
    assert "access-secret" not in captured.out
    assert captured.err == ""
