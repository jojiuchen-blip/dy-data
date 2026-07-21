from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Any

from dydata_cli.client import CliError
from dydata_cli.commands import execute_command
from dydata_cli.credentials import CredentialState
from dydata_cli.parser import parse_args


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
CANONICAL_REQUEST_ID = "req_" + "a" * 32


class FakeCredentialStore:
    def __init__(self, state: CredentialState | None = None) -> None:
        self.state = state
        self.saved: list[CredentialState] = []
        self.clear_count = 0
        self.load_count = 0

    def load(self) -> CredentialState | None:
        self.load_count += 1
        return self.state

    def save(
        self,
        state: CredentialState,
        *,
        expected: CredentialState | None = None,
    ) -> bool:
        if expected is not None and self.state != expected:
            return False
        self.state = state
        self.saved.append(state)
        return True

    def clear(self, *, expected: CredentialState | None = None) -> bool:
        if expected is not None and self.state != expected:
            return False
        self.state = None
        self.clear_count += 1
        return True


class FakeClient:
    def __init__(self) -> None:
        self.refresh_result: dict[str, Any] | Exception | None = None
        self.status_result: dict[str, Any] = auth_status_envelope()
        self.stores_result: dict[str, Any] = stores_envelope()
        self.follow_result: dict[str, Any] = follow_up_envelope()
        self.refresh_calls: list[str] = []
        self.status_calls: list[str] = []
        self.revoke_calls: list[str] = []

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        self.refresh_calls.append(refresh_token)
        if isinstance(self.refresh_result, Exception):
            raise self.refresh_result
        assert self.refresh_result is not None
        return self.refresh_result

    def auth_status(self, access_token: str) -> dict[str, Any]:
        self.status_calls.append(access_token)
        return self.status_result

    def list_stores(self, access_token: str) -> dict[str, Any]:
        return self.stores_result

    def follow_up_stats(self, access_token: str, **_: Any) -> dict[str, Any]:
        return self.follow_result

    def revoke(self, refresh_token: str) -> None:
        self.revoke_calls.append(refresh_token)


def success_envelope(command: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "command": command,
        "schema_version": "1.0",
        "data": data,
        "meta": {"request_id": CANONICAL_REQUEST_ID, "partial": False},
    }


def auth_status_envelope() -> dict[str, Any]:
    return success_envelope(
        "auth.status",
        {
            "authenticated": True,
            "user_id": "user-1",
            "username": "keith",
            "display_name": "Keith",
            "role": "admin",
            "auth_type": "user",
            "store_ids": ["s1"],
            "expires_at": "2026-07-21T12:30:00Z",
        },
    )


def stores_envelope() -> dict[str, Any]:
    payload = success_envelope(
        "stores.list", {"stores": [{"store_id": "s1", "store_name": "Store One"}]}
    )
    payload["scope"] = {"user_id": "user-1", "effective_store_ids": ["s1"]}
    return payload


def metric_values(*, total_count: int = 0) -> dict[str, int | float]:
    return {
        "total_count": total_count,
        "pending_count": 0,
        "followed_count": total_count,
        "other_status_count": 0,
        "action_followed_count": total_count,
        "effective_followed_count": total_count,
        "system_follow_up_rate": 1.0 if total_count else 0.0,
        "action_follow_rate": 1.0 if total_count else 0.0,
    }


def follow_up_envelope(*, stores: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    store_rows = stores or []
    counts = {
        field: sum(int(row[field]) for row in store_rows)
        for field in (
            "total_count",
            "pending_count",
            "followed_count",
            "other_status_count",
            "action_followed_count",
            "effective_followed_count",
        )
    }
    total = counts["total_count"]
    totals = {
        **counts,
        "system_follow_up_rate": (
            round(counts["effective_followed_count"] / total, 4) if total else 0.0
        ),
        "action_follow_rate": (
            round(counts["action_followed_count"] / total, 4) if total else 0.0
        ),
    }
    store_ids = sorted(row["store_id"] for row in store_rows)
    payload = success_envelope(
        "clues.follow-up-stats",
        {"stores": store_rows, "totals": totals},
    )
    payload["metric_version"] = "clue-follow-up-v1"
    payload["scope"] = {
        "user_id": "user-1",
        "requested_store_ids": store_ids,
        "effective_store_ids": store_ids,
    }
    payload["filters"] = {
        "assigned_date_start": "2026-07-01",
        "assigned_date_end": "2026-07-21",
        "timezone": "Asia/Shanghai",
    }
    payload["meta"] = {
        "partial": False,
        "request_id": CANONICAL_REQUEST_ID,
        "generated_at": "2026-07-21T12:00:00Z",
        "data_as_of": "2026-07-21T12:00:00Z",
        "source": "postgres",
    }
    return payload


def state(*, expires_at: datetime) -> CredentialState:
    return CredentialState(
        access_token="old-access-secret",
        access_token_expires_at=expires_at,
        refresh_token="old-refresh-secret",
    )


def run(
    argv: list[str],
    *,
    store: FakeCredentialStore,
    client: FakeClient,
    **kwargs: Any,
) -> tuple[int, str]:
    stream = StringIO()
    parsed = parse_args(argv, today=NOW.date())
    exit_code = execute_command(
        parsed,
        credential_store=store,
        client=client,
        stream=stream,
        now=lambda: NOW,
        **kwargs,
    )
    return exit_code, stream.getvalue()


def test_auth_status_uses_unexpired_access_token_without_refresh() -> None:
    store = FakeCredentialStore(state(expires_at=NOW + timedelta(minutes=10)))
    client = FakeClient()

    exit_code, stdout = run(
        ["auth", "status", "--json"], store=store, client=client
    )

    assert exit_code == 0
    assert json.loads(stdout)["data"]["username"] == "keith"
    assert client.status_calls == ["old-access-secret"]
    assert client.refresh_calls == []
    assert "old-access-secret" not in stdout


def test_expiring_access_token_is_rotated_and_atomically_replaced() -> None:
    store = FakeCredentialStore(state(expires_at=NOW + timedelta(seconds=30)))
    client = FakeClient()
    client.refresh_result = {
        "access_token": "new-access-secret",
        "refresh_token": "new-refresh-secret",
        "access_token_expires_at": "2026-07-21T12:30:00Z",
    }

    exit_code, stdout = run(
        ["auth", "status", "--json"], store=store, client=client
    )

    assert exit_code == 0
    assert client.refresh_calls == ["old-refresh-secret"]
    assert client.status_calls == ["new-access-secret"]
    assert store.saved == [
        CredentialState(
            access_token="new-access-secret",
            access_token_expires_at=datetime(
                2026, 7, 21, 12, 30, tzinfo=timezone.utc
            ),
            refresh_token="new-refresh-secret",
        )
    ]
    assert "secret" not in stdout


def test_refresh_failure_clears_local_credentials() -> None:
    store = FakeCredentialStore(state(expires_at=NOW - timedelta(seconds=1)))
    client = FakeClient()
    client.refresh_result = CliError("AUTH_EXPIRED")

    exit_code, stdout = run(
        ["auth", "status", "--json"], store=store, client=client
    )

    assert exit_code == 3
    assert json.loads(stdout)["error"]["code"] == "AUTH_EXPIRED"
    assert store.clear_count == 1
    assert store.state is None
    assert "secret" not in stdout


def test_missing_credentials_return_auth_required() -> None:
    exit_code, stdout = run(
        ["stores", "list", "--json"],
        store=FakeCredentialStore(),
        client=FakeClient(),
    )

    assert exit_code == 3
    assert json.loads(stdout)["error"]["code"] == "AUTH_REQUIRED"


def test_login_opens_browser_polls_at_server_interval_and_never_prints_tokens() -> None:
    class LoginClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.poll_results = iter(
                [
                    {"status": "authorization_pending"},
                    {
                        "access_token": "login-access-secret",
                        "refresh_token": "login-refresh-secret",
                        "access_token_expires_at": "2026-07-21T12:30:00Z",
                    },
                ]
            )

        def start_device_authorization(self) -> dict[str, Any]:
            return {
                "device_code": "device-secret",
                "user_code": "ABCD1234",
                "verification_uri": "https://app.example.test/auth/cli/authorize",
                "verification_uri_complete": (
                    "https://app.example.test/auth/cli/authorize?user_code=ABCD1234"
                ),
                "expires_in": 10,
                "interval": 2,
            }

        def poll_device_token(self, device_code: str) -> dict[str, Any]:
            assert device_code == "device-secret"
            return next(self.poll_results)

    store = FakeCredentialStore()
    browser_urls: list[str] = []
    sleeps: list[float] = []

    exit_code, stdout = run(
        ["auth", "login"],
        store=store,
        client=LoginClient(),
        browser_open=lambda url: browser_urls.append(url) or True,
        sleep=sleeps.append,
    )

    assert exit_code == 0
    assert browser_urls == [
        "https://app.example.test/auth/cli/authorize?user_code=ABCD1234"
    ]
    assert sleeps == [2]
    assert "ABCD1234" in stdout
    assert "https://app.example.test" in stdout
    assert "device-secret" not in stdout
    assert "login-access-secret" not in stdout
    assert "login-refresh-secret" not in stdout
    assert len(store.saved) == 1


def test_logout_preserves_local_state_when_revoke_is_transiently_unavailable() -> None:
    class FailingRevokeClient(FakeClient):
        def revoke(self, refresh_token: str) -> None:
            self.revoke_calls.append(refresh_token)
            raise CliError("API_UNAVAILABLE")

    store = FakeCredentialStore(state(expires_at=NOW + timedelta(minutes=5)))
    client = FailingRevokeClient()

    exit_code, stdout = run(
        ["auth", "logout"], store=store, client=client
    )

    assert exit_code == 5
    assert client.revoke_calls == ["old-refresh-secret"]
    assert store.state is not None
    assert store.clear_count == 0
    assert "secret" not in stdout


def test_logout_does_not_attempt_a_destructive_clear_when_keyring_load_fails() -> None:
    class FailingLoadStore(FakeCredentialStore):
        def load(self) -> CredentialState | None:
            raise RuntimeError("unsafe refresh-secret")

    store = FailingLoadStore()

    exit_code, stdout = run(
        ["auth", "logout"], store=store, client=FakeClient()
    )

    assert exit_code == 6
    assert store.clear_count == 0
    assert "secret" not in stdout


def test_refresh_auth_failure_compare_deletes_only_the_observed_state() -> None:
    original = state(expires_at=NOW - timedelta(seconds=1))
    store = FakeCredentialStore(original)
    newer = CredentialState(
        access_token="parallel-access-secret",
        access_token_expires_at=NOW + timedelta(minutes=30),
        refresh_token="parallel-refresh-secret",
    )

    class ConcurrentFailureClient(FakeClient):
        def refresh(self, refresh_token: str) -> dict[str, Any]:
            assert refresh_token == original.refresh_token
            store.state = newer
            raise CliError("AUTH_EXPIRED")

    exit_code, stdout = run(
        ["auth", "status", "--json"],
        store=store,
        client=ConcurrentFailureClient(),
    )

    assert exit_code == 3
    assert json.loads(stdout)["error"]["code"] == "AUTH_EXPIRED"
    assert store.state == newer


def test_logout_success_compare_deletes_only_the_observed_state() -> None:
    original = state(expires_at=NOW + timedelta(minutes=5))
    store = FakeCredentialStore(original)
    newer = CredentialState(
        access_token="parallel-access-secret",
        access_token_expires_at=NOW + timedelta(minutes=30),
        refresh_token="parallel-refresh-secret",
    )

    class ConcurrentLogoutClient(FakeClient):
        def revoke(self, refresh_token: str) -> None:
            assert refresh_token == original.refresh_token
            store.state = newer

    exit_code, stdout = run(
        ["auth", "logout"], store=store, client=ConcurrentLogoutClient()
    )

    assert exit_code == 0
    assert stdout == "Logged out.\n"
    assert store.state == newer


def test_follow_up_json_is_forwarded_as_one_document() -> None:
    store = FakeCredentialStore(state(expires_at=NOW + timedelta(minutes=5)))
    client = FakeClient()
    client.follow_result = follow_up_envelope(
        stores=[{"store_id": "s1", "store_name": "Store One", **metric_values(total_count=2)}],
    )

    exit_code, stdout = run(
        ["clues", "follow-up-stats", "--output", "json"],
        store=store,
        client=client,
    )

    assert exit_code == 0
    assert json.loads(stdout) == client.follow_result
    assert stdout.count("\n") == 1


def test_follow_up_table_renders_only_aggregate_fields() -> None:
    store = FakeCredentialStore(state(expires_at=NOW + timedelta(minutes=5)))
    client = FakeClient()
    client.follow_result = follow_up_envelope(
        stores=[
            {
                "store_id": "s1",
                "store_name": "Store One",
                **metric_values(total_count=2),
            }
        ],
    )

    exit_code, stdout = run(
        ["clues", "follow-up-stats", "--output", "table"],
        store=store,
        client=client,
    )

    assert exit_code == 0
    assert "Store One" in stdout
    assert "13800000000" not in stdout
    assert "private" not in stdout
    assert "store_id" not in stdout
