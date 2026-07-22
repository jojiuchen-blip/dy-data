from __future__ import annotations

import hashlib
import getpass
import json
import warnings
from datetime import datetime, timezone
from io import StringIO
from typing import Any

import pytest

from dydata_cli.client import CliError
from dydata_cli.commands import _save_new_credential, execute_command
from dydata_cli.credentials import CredentialState
from dydata_cli.interactive_auth import LoginIdentity
from dydata_cli.parser import parse_args


class _RedactedPassword(str):
    def __repr__(self) -> str:
        return "<redacted-password>"


def _password_sentinel() -> _RedactedPassword:
    return _RedactedPassword("".join(("test", "-password", "-sentinel")))


def _token_value(kind: str) -> str:
    return "".join((kind, "-token", "-sentinel"))


def _state(prefix: str = "old") -> CredentialState:
    return CredentialState(
        access_token=_token_value(f"{prefix}-access"),
        access_token_expires_at=datetime(
            2026, 7, 22, 12, 30, tzinfo=timezone.utc
        ),
        refresh_token=_token_value(f"{prefix}-refresh"),
    )


class FakeCredentialStore:
    _unset = object()

    def __init__(self, state: CredentialState | None = None) -> None:
        self.state = state
        self.saved: list[CredentialState] = []

    def load(self) -> CredentialState | None:
        return self.state

    def save(
        self,
        state: CredentialState,
        *,
        expected: CredentialState | None | object = _unset,
    ) -> bool:
        if expected is not self._unset and self.state != expected:
            return False
        self.state = state
        self.saved.append(state)
        return True


class FakeDeviceClient:
    def __init__(self) -> None:
        self.start_calls = 0
        self.poll_calls: list[str] = []
        self.revoke_calls: list[str] = []

    def start_device_authorization(self) -> dict[str, Any]:
        self.start_calls += 1
        return {
            "device_code": "device-code-sentinel",
            "user_code": "ABCD1234",
            "verification_uri": "https://app.example.test/auth/cli/authorize",
            "verification_uri_complete": (
                "https://app.example.test/auth/cli/authorize?user_code=ABCD1234"
            ),
            "expires_in": 10,
            "interval": 2,
        }

    def poll_device_token(self, device_code: str) -> dict[str, Any]:
        self.poll_calls.append(device_code)
        return {
            "access_token": _token_value("login-access"),
            "refresh_token": _token_value("login-refresh"),
            "access_token_expires_at": "2026-07-22T12:30:00Z",
        }

    def revoke(self, refresh_token: str) -> None:
        self.revoke_calls.append(refresh_token)


class FakeInteractiveAuthSession:
    def __init__(
        self,
        *,
        identity: LoginIdentity | None = None,
        login_error: CliError | None = None,
    ) -> None:
        self.identity = identity or LoginIdentity(
            username="cli.acceptance",
            role="store",
            store_scope_mode="specified",
            store_ids=("store-a", "store-b", "store-c"),
        )
        self.login_error = login_error
        self.login_usernames: list[str] = []
        self.password_digests: list[bytes] = []
        self.approve_calls: list[str] = []
        self.closed = False

    def __enter__(self) -> "FakeInteractiveAuthSession":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.closed = True

    def login(self, username: str, password: str) -> LoginIdentity:
        self.login_usernames.append(username)
        self.password_digests.append(hashlib.sha256(password.encode()).digest())
        if self.login_error is not None:
            raise self.login_error
        return self.identity

    def approve_device_authorization(self, user_code: str) -> None:
        self.approve_calls.append(user_code)


def _run_login(
    argv: list[str],
    *,
    store: FakeCredentialStore,
    client: FakeDeviceClient,
    auth_session: FakeInteractiveAuthSession,
    text_answers: list[str] | None = None,
    is_interactive: bool = True,
    password: str | None = None,
    password_warning: bool = False,
    text_eof_at: int | None = None,
) -> tuple[int, str, list[str], list[str]]:
    output = StringIO()
    prompts: list[str] = []
    password_prompts: list[str] = []
    answers = iter(
        ["cli.acceptance", "y"] if text_answers is None else text_answers
    )

    def text_input(prompt: str) -> str:
        prompts.append(prompt)
        if text_eof_at == len(prompts):
            raise EOFError("terminal input ended")
        return next(answers)

    def password_input(prompt: str) -> str:
        password_prompts.append(prompt)
        if password_warning:
            warnings.warn("terminal echo cannot be disabled", getpass.GetPassWarning)
        return password if password is not None else _password_sentinel()

    exit_code = execute_command(
        parse_args(argv),
        credential_store=store,
        client=client,
        stream=output,
        interactive_auth_factory=lambda: auth_session,
        text_input=text_input,
        password_input=password_input,
        is_interactive_terminal=lambda: is_interactive,
        sleep=lambda _: None,
    )
    return exit_code, output.getvalue(), prompts, password_prompts


def test_default_login_uses_hidden_password_confirms_identity_and_saves() -> None:
    store = FakeCredentialStore()
    client = FakeDeviceClient()
    auth_session = FakeInteractiveAuthSession()

    exit_code, output, prompts, password_prompts = _run_login(
        ["auth", "login"],
        store=store,
        client=client,
        auth_session=auth_session,
    )

    assert exit_code == 0
    assert prompts == ["Username: ", "Authorize this CLI credential? [y/N]: "]
    assert password_prompts == ["Password: "]
    assert auth_session.login_usernames == ["cli.acceptance"]
    assert auth_session.password_digests == [
        hashlib.sha256(_password_sentinel().encode()).digest()
    ]
    assert auth_session.approve_calls == ["ABCD1234"]
    assert auth_session.closed is True
    assert client.start_calls == 1
    assert client.poll_calls == ["device-code-sentinel"]
    assert len(store.saved) == 1
    assert "cli.acceptance" in output
    assert "Role: store" in output
    assert "Store scope: 3 stores" in output
    assert "Authorization complete." in output
    for sensitive_value in (
        _password_sentinel(),
        "device-code-sentinel",
        _token_value("login-access"),
        _token_value("login-refresh"),
    ):
        assert sensitive_value not in output


def test_terminal_login_rejects_non_tty_before_input_or_network() -> None:
    store = FakeCredentialStore()
    client = FakeDeviceClient()
    auth_session = FakeInteractiveAuthSession()

    exit_code, output, prompts, password_prompts = _run_login(
        ["auth", "login"],
        store=store,
        client=client,
        auth_session=auth_session,
        is_interactive=False,
    )

    assert exit_code == 2
    assert json.loads(output)["error"]["code"] == "INTERACTIVE_REQUIRED"
    assert prompts == []
    assert password_prompts == []
    assert client.start_calls == 0
    assert auth_session.login_usernames == []
    assert store.saved == []


def test_getpass_fallback_warning_fails_closed_before_login_or_network() -> None:
    store = FakeCredentialStore()
    client = FakeDeviceClient()
    auth_session = FakeInteractiveAuthSession()

    exit_code, output, prompts, password_prompts = _run_login(
        ["auth", "login"],
        store=store,
        client=client,
        auth_session=auth_session,
        password_warning=True,
    )

    assert exit_code == 2
    assert json.loads(output)["error"]["code"] == "INTERACTIVE_REQUIRED"
    assert prompts == ["Username: "]
    assert password_prompts == ["Password: "]
    assert client.start_calls == 0
    assert auth_session.login_usernames == []
    assert auth_session.approve_calls == []
    assert client.poll_calls == []
    assert store.saved == []
    assert _password_sentinel() not in output


def test_username_eof_maps_to_interactive_required_before_password_or_network() -> None:
    store = FakeCredentialStore()
    client = FakeDeviceClient()
    auth_session = FakeInteractiveAuthSession()

    exit_code, output, prompts, password_prompts = _run_login(
        ["auth", "login"],
        store=store,
        client=client,
        auth_session=auth_session,
        text_eof_at=1,
    )

    assert exit_code == 2
    assert json.loads(output)["error"]["code"] == "INTERACTIVE_REQUIRED"
    assert prompts == ["Username: "]
    assert password_prompts == []
    assert client.start_calls == 0
    assert auth_session.login_usernames == []
    assert store.saved == []


def test_confirmation_eof_closes_session_without_creating_device_grant() -> None:
    store = FakeCredentialStore()
    client = FakeDeviceClient()
    auth_session = FakeInteractiveAuthSession()

    exit_code, output, prompts, _ = _run_login(
        ["auth", "login"],
        store=store,
        client=client,
        auth_session=auth_session,
        text_eof_at=2,
    )

    assert exit_code == 2
    assert json.loads(output.splitlines()[-1])["error"]["code"] == (
        "INTERACTIVE_REQUIRED"
    )
    assert prompts == ["Username: ", "Authorize this CLI credential? [y/N]: "]
    assert auth_session.closed is True
    assert auth_session.approve_calls == []
    assert client.start_calls == 0
    assert client.poll_calls == []
    assert store.saved == []


def test_user_cancellation_closes_web_session_without_approving_or_saving() -> None:
    store = FakeCredentialStore()
    client = FakeDeviceClient()
    auth_session = FakeInteractiveAuthSession()

    exit_code, output, _, _ = _run_login(
        ["auth", "login"],
        store=store,
        client=client,
        auth_session=auth_session,
        text_answers=["cli.acceptance", "n"],
    )

    assert exit_code == 3
    assert output.endswith("Authorization cancelled.\n")
    assert auth_session.approve_calls == []
    assert auth_session.closed is True
    assert client.start_calls == 0
    assert client.poll_calls == []
    assert store.saved == []
    assert _password_sentinel() not in output


def test_invalid_credentials_are_sanitized_and_do_not_approve_or_poll() -> None:
    store = FakeCredentialStore()
    client = FakeDeviceClient()
    auth_session = FakeInteractiveAuthSession(login_error=CliError("AUTH_FAILED"))

    exit_code, output, _, _ = _run_login(
        ["auth", "login"],
        store=store,
        client=client,
        auth_session=auth_session,
    )

    assert exit_code == 3
    assert json.loads(output.splitlines()[-1])["error"]["code"] == "AUTH_FAILED"
    assert auth_session.closed is True
    assert auth_session.approve_calls == []
    assert client.start_calls == 0
    assert client.poll_calls == []
    assert store.saved == []
    assert _password_sentinel() not in output


@pytest.mark.parametrize("argv", [["auth", "login"], ["auth", "login", "--browser"]])
def test_existing_credential_is_a_no_network_no_overwrite_noop(argv: list[str]) -> None:
    original = _state()
    store = FakeCredentialStore(original)
    client = FakeDeviceClient()
    auth_session = FakeInteractiveAuthSession()

    exit_code, output, prompts, password_prompts = _run_login(
        argv,
        store=store,
        client=client,
        auth_session=auth_session,
        is_interactive=False,
    )

    assert exit_code == 0
    assert "already exists" in output
    assert "auth logout" in output
    assert store.state == original
    assert store.saved == []
    assert client.start_calls == 0
    assert prompts == []
    assert password_prompts == []


def test_concurrent_credential_save_never_overwrites_and_revokes_new_token() -> None:
    concurrent_state = _state("concurrent")

    class RacingStore(FakeCredentialStore):
        def save(
            self,
            state: CredentialState,
            *,
            expected: CredentialState | None | object = FakeCredentialStore._unset,
        ) -> bool:
            assert expected is None
            self.state = concurrent_state
            return False

    store = RacingStore()
    client = FakeDeviceClient()

    exit_code, output, _, _ = _run_login(
        ["auth", "login"],
        store=store,
        client=client,
        auth_session=FakeInteractiveAuthSession(),
    )

    assert exit_code == 3
    assert json.loads(output.splitlines()[-1])["error"]["code"] == "AUTH_FAILED"
    assert store.state == concurrent_state
    assert store.saved == []
    assert client.revoke_calls == [_token_value("login-refresh")]
    assert _token_value("login-refresh") not in output


def test_revoke_cleanup_failure_does_not_mask_concurrent_save_outcome() -> None:
    concurrent_state = _state("concurrent")

    class RacingStore(FakeCredentialStore):
        def save(
            self,
            state: CredentialState,
            *,
            expected: CredentialState | None | object = FakeCredentialStore._unset,
        ) -> bool:
            assert expected is None
            self.state = concurrent_state
            return False

    class FailingRevokeClient(FakeDeviceClient):
        def revoke(self, refresh_token: str) -> None:
            self.revoke_calls.append(refresh_token)
            raise RuntimeError("unsafe revoke failure sentinel")

    store = RacingStore()
    client = FailingRevokeClient()

    exit_code, output, _, _ = _run_login(
        ["auth", "login"],
        store=store,
        client=client,
        auth_session=FakeInteractiveAuthSession(),
    )

    assert exit_code == 3
    assert json.loads(output.splitlines()[-1])["error"]["code"] == "AUTH_FAILED"
    assert store.state == concurrent_state
    assert client.revoke_calls == [_token_value("login-refresh")]
    assert "revoke failure sentinel" not in output


def test_revoke_cleanup_failure_does_not_mask_keyring_save_exception() -> None:
    class KeyringSaveError(RuntimeError):
        pass

    class FailingStore(FakeCredentialStore):
        def save(
            self,
            state: CredentialState,
            *,
            expected: CredentialState | None | object = FakeCredentialStore._unset,
        ) -> bool:
            assert expected is None
            raise KeyringSaveError("original keyring failure sentinel")

    class FailingRevokeClient(FakeDeviceClient):
        def revoke(self, refresh_token: str) -> None:
            self.revoke_calls.append(refresh_token)
            raise ValueError("cleanup revoke failure sentinel")

    client = FailingRevokeClient()
    new_state = _state("login")

    with pytest.raises(KeyringSaveError, match="original keyring failure sentinel"):
        _save_new_credential(FailingStore(), client, new_state)

    assert client.revoke_calls == [new_state.refresh_token]


def test_keyring_save_error_best_effort_revokes_the_unstored_new_token() -> None:
    class FailingStore(FakeCredentialStore):
        def save(
            self,
            state: CredentialState,
            *,
            expected: CredentialState | None | object = FakeCredentialStore._unset,
        ) -> bool:
            assert expected is None
            raise RuntimeError("unsafe keyring failure sentinel")

    store = FailingStore()
    client = FakeDeviceClient()

    exit_code, output, _, _ = _run_login(
        ["auth", "login"],
        store=store,
        client=client,
        auth_session=FakeInteractiveAuthSession(),
    )

    assert exit_code == 6
    assert json.loads(output.splitlines()[-1])["error"]["code"] == "INTERNAL_ERROR"
    assert client.revoke_calls == [_token_value("login-refresh")]
    assert _token_value("login-refresh") not in output
    assert "keyring failure sentinel" not in output


def test_password_environment_variable_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DYDATA_PASSWORD", "environment-password-sentinel")
    auth_session = FakeInteractiveAuthSession()

    exit_code, output, _, _ = _run_login(
        ["auth", "login"],
        store=FakeCredentialStore(),
        client=FakeDeviceClient(),
        auth_session=auth_session,
        password=_password_sentinel(),
    )

    assert exit_code == 0
    assert auth_session.password_digests == [
        hashlib.sha256(_password_sentinel().encode()).digest()
    ]
    assert "environment-password-sentinel" not in output
