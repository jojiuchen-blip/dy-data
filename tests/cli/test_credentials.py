from __future__ import annotations

import json
from datetime import datetime, timezone

from dydata_cli.credentials import CredentialState, CredentialStore


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def credential_state() -> CredentialState:
    return CredentialState(
        access_token="access-secret",
        access_token_expires_at=datetime(2026, 7, 21, 12, 30, tzinfo=timezone.utc),
        refresh_token="refresh-secret",
    )


def test_credential_store_uses_one_keyring_json_value() -> None:
    keyring = FakeKeyring()
    store = CredentialStore(keyring_backend=keyring)

    store.save(credential_state())

    assert set(keyring.values) == {("dydata-cli", "default")}
    payload = json.loads(keyring.values[("dydata-cli", "default")])
    assert payload == {
        "access_token": "access-secret",
        "access_token_expires_at": "2026-07-21T12:30:00+00:00",
        "refresh_token": "refresh-secret",
    }
    assert store.load() == credential_state()


def test_credential_store_clear_removes_only_keyring_value() -> None:
    keyring = FakeKeyring()
    store = CredentialStore(keyring_backend=keyring)
    store.save(credential_state())

    store.clear()

    assert store.load() is None


def test_credential_store_clears_invalid_state_without_echoing_it() -> None:
    keyring = FakeKeyring()
    keyring.values[("dydata-cli", "default")] = "not-json-access-secret"
    store = CredentialStore(keyring_backend=keyring)

    assert store.load() is None
    assert keyring.values == {}


def test_credential_state_repr_never_contains_tokens() -> None:
    rendered = repr(credential_state())

    assert "access-secret" not in rendered
    assert "refresh-secret" not in rendered
    assert "redacted" in rendered.lower()
